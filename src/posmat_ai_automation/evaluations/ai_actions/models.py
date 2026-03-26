"""Data models for Posmat AI action runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

OUTPUT_COLUMNS = [
    "row_index",
    "user_id",
    "chat_id",
    "triggered_ai_action_name",
    "ai_action_output",
    "input",
]


@dataclass(frozen=True)
class PosmatActionInput:
    """One CSV row to process."""

    row_index: int
    row_data: Mapping[str, Any]


@dataclass
class PosmatActionRecord:
    """CSV-ready result for one processed row."""

    row_index: int
    user_id: str = ""
    chat_id: str = ""
    triggered_ai_action_name: str = ""
    ai_action_output: str = ""
    input: str = ""
    status: str = "failed"
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_index": self.row_index,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "triggered_ai_action_name": self.triggered_ai_action_name,
            "ai_action_output": self.ai_action_output,
            "input": self.input,
        }
