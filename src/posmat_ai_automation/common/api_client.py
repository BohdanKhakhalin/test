"""HTTP client and SSE parsing for the Posmat public API."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import requests

LOGGER = logging.getLogger("posmat_ai_actions")
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class ApiResearchConfig:
    """Static API configuration confirmed from API research."""

    base_url: str
    bot_public_id: str
    origin: str
    create_user_path: str
    update_attributes_path: str
    trigger_action_path: str
    updatable_attribute_types: Tuple[str, ...] = ("WIDGET",)

    @property
    def create_user_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.create_user_path.lstrip('/')}"

    def update_attributes_url(self, user_id: str) -> str:
        return (
            f"{self.base_url.rstrip('/')}/"
            f"{self.update_attributes_path.format(user_id=user_id).lstrip('/')}"
        )

    def trigger_action_url(self, user_id: str) -> str:
        return (
            f"{self.base_url.rstrip('/')}/"
            f"{self.trigger_action_path.format(bot_public_id=self.bot_public_id, user_id=user_id).lstrip('/')}"
        )


@dataclass
class TriggerParseResult:
    """Normalized action details extracted from an SSE response."""

    action_name: str = ""
    ai_action_output: str = ""


class PosmatAPIClient:
    """Thin API client for Posmat create-user, attribute update, and chat calls."""

    def __init__(self, config: ApiResearchConfig, api_token: str) -> None:
        self.config = config
        self.api_token = api_token

    def create_user(
        self,
        *,
        timeout: int,
        dry_run: bool,
        user_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        headers = {"Authorization": self.api_token}

        LOGGER.info("step=create_user dry_run=%s", dry_run)
        if dry_run:
            LOGGER.info(
                "dry_run create_user url=%s headers=%s payload=%s",
                self.config.create_user_url,
                headers,
                user_payload,
            )
            return "dry-run-user-id", "dry-run-chat-id"

        try:
            response = self._request_with_retries(
                "POST",
                self.config.create_user_url,
                headers=headers,
                json_payload=user_payload,
                timeout=timeout,
            )
        except RuntimeError:
            if not user_payload:
                raise
            LOGGER.warning(
                "step=create_user retry_without_payload=true payload=%s",
                user_payload,
            )
            response = self._request_with_retries(
                "POST",
                self.config.create_user_url,
                headers=headers,
                timeout=timeout,
            )
        body = safe_json(response) or {}
        data = body.get("data", {})
        user_id = str(data.get("userId", "")).strip()
        chat_id = str(data.get("chatId", "")).strip()

        if not user_id or not chat_id:
            raise ValueError("Create user response is missing data.userId or data.chatId")

        return user_id, chat_id

    def update_user_attributes(
        self,
        *,
        chat_id: str,
        payload: Dict[str, Any],
        timeout: int,
        dry_run: bool,
    ) -> None:
        headers = {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
            "accept": "*/*",
            "Origin": self.config.origin,
        }
        url = self.config.update_attributes_url(chat_id)

        LOGGER.info(
            "step=update_user_attributes dry_run=%s chat_id=%s attribute_count=%s",
            dry_run,
            chat_id,
            len(payload.get("attributes", {})),
        )
        if dry_run:
            LOGGER.info("dry_run update_user_attributes url=%s payload=%s", url, payload)
            return

        self._request_with_retries(
            "PUT",
            url,
            headers=headers,
            json_payload=payload,
            timeout=timeout,
        )

    def trigger_action(
        self,
        *,
        user_id: str,
        payload: List[Dict[str, str]],
        timeout: int,
        dry_run: bool,
    ) -> TriggerParseResult:
        headers = {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
        }
        url = self.config.trigger_action_url(user_id)

        LOGGER.info("step=trigger_action dry_run=%s user_id=%s", dry_run, user_id)
        if dry_run:
            LOGGER.info("dry_run trigger_action url=%s payload=%s", url, payload)
            return TriggerParseResult()

        response = self._request_with_retries(
            "POST",
            url,
            headers=headers,
            json_payload=payload,
            timeout=timeout,
        )
        return extract_trigger_result(response.text)

    def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        json_payload: Optional[Any] = None,
        timeout: int,
        max_attempts: int = 3,
    ) -> requests.Response:
        last_error: Optional[Exception] = None
        session = get_thread_session()

        for attempt in range(1, max_attempts + 1):
            try:
                response = session.request(
                    method=method,
                    url=url,
                    headers=dict(headers or {}),
                    json=json_payload,
                    timeout=timeout,
                )
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                    wait_seconds = 2 ** (attempt - 1)
                    LOGGER.warning(
                        "step=request retry=%s status=%s url=%s wait=%ss",
                        attempt,
                        response.status_code,
                        url,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                response_excerpt = ""
                if response is not None:
                    response_excerpt = f" response={response.text[:500]!r}"
                last_error = exc
                if attempt >= max_attempts:
                    last_error = RuntimeError(f"{exc}{response_excerpt}")
                    break
                wait_seconds = 2 ** (attempt - 1)
                LOGGER.warning(
                    "step=request retry=%s error=%s%s url=%s wait=%ss",
                    attempt,
                    exc,
                    response_excerpt,
                    url,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"Request failed after retries: {last_error}")


def create_api_research_config(base_url: str, bot_public_id: str) -> ApiResearchConfig:
    """Build researched route configuration from environment values."""
    from urllib.parse import urlsplit

    parts = urlsplit(base_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    return ApiResearchConfig(
        base_url=base_url.rstrip("/"),
        bot_public_id=bot_public_id,
        origin=origin,
        create_user_path=f"/public/v1/bots/{bot_public_id}/ai-chat/users",
        update_attributes_path="/public/v1/users/{user_id}/attributes",
        trigger_action_path=f"/public/v1/bots/{bot_public_id}/ai-chat/users/{{user_id}}/chat",
    )


def create_session() -> requests.Session:
    return requests.Session()


def get_thread_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = create_session()
        _THREAD_LOCAL.session = session
    return session


def safe_json(response: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def parse_sse_events(raw_text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    current_event = ""
    current_data_parts: List[str] = []

    def flush() -> None:
        nonlocal current_event, current_data_parts
        if not current_event and not current_data_parts:
            return
        data_text = "\n".join(current_data_parts).strip()
        data_json: Optional[Any] = None
        if data_text:
            try:
                data_json = json.loads(data_text)
            except json.JSONDecodeError:
                data_json = None
        events.append(
            {
                "event": current_event.strip(),
                "data_text": data_text,
                "data_json": data_json,
            }
        )
        current_event = ""
        current_data_parts = []

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("event:"):
            current_event = stripped.partition(":")[2].strip()
            continue
        if stripped.startswith("data:"):
            current_data_parts.append(stripped.partition(":")[2].strip())

    flush()
    return events


def search_first_value(payload: Any, keys: Iterable[str]) -> Optional[Any]:
    wanted = set(keys)
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in wanted and value not in (None, "", []):
                return value
            nested = search_first_value(value, wanted)
            if nested not in (None, "", []):
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = search_first_value(item, wanted)
            if nested not in (None, "", []):
                return nested
    return None


def normalize_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def extract_trigger_result(raw_text: str) -> TriggerParseResult:
    result = TriggerParseResult()
    events = parse_sse_events(raw_text)

    for event in events:
        event_name = event.get("event", "")
        payload = event.get("data_json")
        data_text = event.get("data_text", "")

        if isinstance(payload, dict):
            if not result.action_name and event_name in {"ai_action_input", "tool_call"}:
                candidate = search_first_value(
                    payload,
                    [
                        "action_name",
                        "ai_action_name",
                        "action_internal_name",
                        "name",
                        "actionName",
                        "aiActionName",
                        "tool_name",
                        "toolName",
                    ],
                )
                if candidate:
                    result.action_name = normalize_output(candidate)

            if event_name == "ai_action_output":
                candidate_output = search_first_value(
                    payload,
                    ["ai_action_output", "output", "result", "content", "text", "message"],
                )
                if candidate_output is None:
                    candidate_output = payload
                result.ai_action_output = normalize_output(candidate_output)

        elif event_name == "ai_action_output" and data_text:
            result.ai_action_output = data_text

    if not result.ai_action_output:
        for event in reversed(events):
            payload = event.get("data_json")
            data_text = event.get("data_text", "")
            if isinstance(payload, dict):
                result.ai_action_output = normalize_output(payload)
                break
            if data_text:
                result.ai_action_output = data_text
                break

    return result
