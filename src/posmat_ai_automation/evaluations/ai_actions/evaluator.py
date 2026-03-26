"""Evaluator for Posmat AI action automation."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Mapping, Optional, Sequence

from posmat_ai_automation.common.api_client import PosmatAPIClient
from posmat_ai_automation.common.evaluator import BaseEvaluator
from posmat_ai_automation.evaluations.ai_actions.models import (
    PosmatActionInput,
    PosmatActionRecord,
)

LOGGER = logging.getLogger("posmat_ai_actions")
RESERVED_INPUT_COLUMNS = {"input", "trigger_input", "row_index"}
ALLOWED_CHATBOT_ATTRIBUTES = {
    "location",
    "order_id",
    "refund_reason",
    "shipping_priority",
    "payment_method",
    "payment_issue",
}
CONTEXT_ATTRIBUTE_ORDER = (
    "order_id",
    "location",
    "country",
    "refund_reason",
    "shipping_priority",
    "payment_method",
    "payment_issue",
)


class PosmatAIActionEvaluator(BaseEvaluator):
    """Run Posmat AI actions for CSV-defined input rows."""

    def __init__(
        self,
        api_client: PosmatAPIClient,
        attribute_catalog: Mapping[str, Mapping[str, str]],
        updatable_attribute_types: Sequence[str],
    ) -> None:
        self.api_client = api_client
        self.attribute_catalog = attribute_catalog
        self.updatable_attribute_types = tuple(updatable_attribute_types)

    def evaluate(
        self,
        test_input: PosmatActionInput,
        **kwargs: Any,
    ) -> PosmatActionRecord:
        timeout = int(kwargs.get("timeout"))
        dry_run = bool(kwargs.get("dry_run", False))
        row = test_input.row_data
        result = PosmatActionRecord(row_index=test_input.row_index)

        if self._is_empty_row(row):
            result.error_message = "Empty input row"
            return result

        input_text = str(row.get("input") or row.get("trigger_input") or "").strip()
        result.input = input_text
        if not input_text:
            result.error_message = "Missing required input text"
            return result

        try:
            user_payload = self._build_user_payload(row)
            user_id, chat_id = self.api_client.create_user(
                timeout=timeout,
                dry_run=dry_run,
                user_payload=user_payload,
            )
            result.user_id = user_id
            result.chat_id = chat_id

            attributes_payload = self._build_attributes_payload(row)
            if attributes_payload.get("attributes"):
                self.api_client.update_user_attributes(
                    chat_id=chat_id,
                    payload=attributes_payload,
                    timeout=timeout,
                    dry_run=dry_run,
                )
            else:
                LOGGER.info(
                    "step=update_user_attributes skipped=true row_index=%s",
                    test_input.row_index,
                )

            trigger_payload = self._build_trigger_payload(input_text, row)
            trigger_result = self.api_client.trigger_action(
                user_id=user_id,
                payload=trigger_payload,
                timeout=timeout,
                dry_run=dry_run,
            )
            result.triggered_ai_action_name = trigger_result.action_name
            result.ai_action_output = trigger_result.ai_action_output
            result.status = "dry_run" if dry_run else "success"
            return result
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error_message = str(exc)
            LOGGER.exception(
                "step=process_row_failed row_index=%s error=%s",
                test_input.row_index,
                exc,
            )
            return result

    def run(
        self,
        test_inputs: Sequence[PosmatActionInput],
        *,
        workers: int,
        timeout: int,
        dry_run: bool,
    ) -> List[PosmatActionRecord]:
        results: List[Optional[PosmatActionRecord]] = [None] * len(test_inputs)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(
                    self.evaluate,
                    test_input,
                    timeout=timeout,
                    dry_run=dry_run,
                ): test_input.row_index
                for test_input in test_inputs
            }

            for future in as_completed(future_map):
                row_index = future_map[future]
                results[row_index - 1] = future.result()

        return [result for result in results if result is not None]

    def _is_empty_row(self, row: Mapping[str, Any]) -> bool:
        return not any(str(value).strip() for value in row.values())

    def _normalize_scalar(self, value: Any) -> Optional[Any]:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

        if text.lower() in {"true", "false", "null"}:
            try:
                return json.loads(text.lower())
            except json.JSONDecodeError:
                return text

        return text

    def _build_user_payload(self, row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        user_field_map = {
            "username": "username",
            "email": "email",
            "user_email": "user_email",
            "language": "language",
            "first_name": "firstName",
            "last_name": "lastName",
            "full_name": "fullName",
            "display_name": "displayName",
        }

        for row_key, payload_key in user_field_map.items():
            normalized = self._normalize_scalar(row.get(row_key))
            if normalized is not None:
                payload[payload_key] = normalized
        return payload or None

    def _build_attributes_payload(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        allowed_types = set(self.updatable_attribute_types)
        attributes: Dict[str, Any] = {}
        skipped: List[str] = []

        for raw_key, raw_value in row.items():
            key = str(raw_key).strip()
            if key in RESERVED_INPUT_COLUMNS:
                continue

            normalized = self._normalize_scalar(raw_value)
            if normalized is None:
                continue

            candidate_name = key[5:] if key.startswith("attr_") else key
            metadata = self.attribute_catalog.get(candidate_name)
            if not metadata:
                continue

            attr_type = metadata.get("type", "")
            if attr_type in allowed_types or candidate_name in ALLOWED_CHATBOT_ATTRIBUTES:
                attributes[candidate_name] = normalized
            else:
                skipped.append(f"{candidate_name}({attr_type or 'UNKNOWN'})")

        attributes_json = self._normalize_scalar(row.get("attributes_json"))
        if isinstance(attributes_json, dict):
            for key, value in attributes_json.items():
                metadata = self.attribute_catalog.get(key)
                if not metadata or value is None:
                    continue
                attr_type = metadata.get("type", "")
                if attr_type in allowed_types or key in ALLOWED_CHATBOT_ATTRIBUTES:
                    attributes[key] = value
                else:
                    skipped.append(f"{key}({attr_type or 'UNKNOWN'})")

        if skipped:
            LOGGER.info(
                "step=build_attributes_payload skipped_non_public_attributes=%s",
                ", ".join(sorted(set(skipped))),
            )

        return {"attributes": attributes}

    def _build_trigger_payload(
        self,
        input_text: str,
        row: Mapping[str, Any],
    ) -> List[Dict[str, str]]:
        context_parts: List[str] = []
        for key in CONTEXT_ATTRIBUTE_ORDER:
            normalized = self._normalize_scalar(row.get(key))
            if normalized is None:
                continue
            context_parts.append(f"{key}={normalized}")

        if not context_parts:
            content = input_text
        else:
            content = (
                f"{input_text}\n\n"
                "Structured customer context:\n"
                f"{'; '.join(context_parts)}"
            )

        return [{"role": "user", "content": content}]
