"""Evaluator for Posmat AI action automation."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
COUNTRY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("united states", "United States"),
    ("netherlands", "Netherlands"),
    ("germany", "Germany"),
    ("canada", "Canada"),
    ("spain", "Spain"),
    ("italy", "Italy"),
    ("france", "France"),
)
SHIPPING_PRIORITY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("overnight", "overnight"),
    ("express", "express"),
    ("standard", "standard"),
    ("economy", "economy"),
)
PAYMENT_METHOD_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("apple pay", "Apple Pay"),
    ("bank transfer", "bank transfer"),
    ("paypal", "PayPal"),
    ("card", "card"),
)
REFUND_REASON_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("damaged item", "damaged item"),
    ("late delivery", "late delivery"),
    ("changed mind", "changed mind"),
    ("wrong size", "wrong size"),
)
PAYMENT_ISSUE_PATTERNS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("declined",), "card declined"),
    (("authorization", "hanging"), "authorization pending"),
    (("authorization", "never returns"), "authorization pending"),
    (("verify again",), "device verification failed"),
    (("checkout drops",), "device verification failed"),
    (("unpaid",), "payment pending"),
    (("payment pending",), "payment pending"),
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

            attributes_payload = self._build_attributes_payload(row, input_text)
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

    def _build_attributes_payload(
        self,
        row: Mapping[str, Any],
        input_text: str,
    ) -> Dict[str, Any]:
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

        for key, value in self._infer_context_from_input(input_text).items():
            metadata = self.attribute_catalog.get(key)
            if not metadata:
                continue
            attr_type = metadata.get("type", "")
            if attr_type in allowed_types or key in ALLOWED_CHATBOT_ATTRIBUTES:
                attributes.setdefault(key, value)
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
        context = self._collect_context(row, input_text)
        for key in CONTEXT_ATTRIBUTE_ORDER:
            normalized = context.get(key)
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

    def _collect_context(
        self,
        row: Mapping[str, Any],
        input_text: str,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {}
        for key in CONTEXT_ATTRIBUTE_ORDER:
            normalized = self._normalize_scalar(row.get(key))
            if normalized is not None:
                context[key] = normalized

        for key, value in self._infer_context_from_input(input_text).items():
            context.setdefault(key, value)

        if "location" in context and "country" not in context:
            context["country"] = context["location"]
        return context

    def _infer_context_from_input(self, input_text: str) -> Dict[str, str]:
        text = input_text.strip()
        lowered = text.lower()
        inferred: Dict[str, str] = {}

        order_match = re.search(r"\bORD-\d+\b", text, flags=re.IGNORECASE)
        if order_match:
            inferred["order_id"] = order_match.group(0).upper()

        location = self._match_phrase(lowered, COUNTRY_PATTERNS)
        if location:
            inferred["location"] = location
            inferred["country"] = location

        shipping_priority = self._match_phrase(lowered, SHIPPING_PRIORITY_PATTERNS)
        if shipping_priority:
            inferred["shipping_priority"] = shipping_priority

        payment_method = self._match_phrase(lowered, PAYMENT_METHOD_PATTERNS)
        if payment_method:
            inferred["payment_method"] = payment_method

        refund_reason = self._match_phrase(lowered, REFUND_REASON_PATTERNS)
        if refund_reason:
            inferred["refund_reason"] = refund_reason

        for required_terms, canonical_value in PAYMENT_ISSUE_PATTERNS:
            if all(term in lowered for term in required_terms):
                inferred["payment_issue"] = canonical_value
                break

        return inferred

    def _match_phrase(
        self,
        lowered_text: str,
        patterns: Sequence[Tuple[str, str]],
    ) -> Optional[str]:
        for needle, value in patterns:
            if needle in lowered_text:
                return value
        return None
