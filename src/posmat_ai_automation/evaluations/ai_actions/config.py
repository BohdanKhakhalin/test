"""Configuration for the AI action evaluation flow."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from posmat_ai_automation.common.config import BaseConfig

DEFAULT_TIMEOUT = 60
DEFAULT_BOT_CONTENT_PATH = Path(r"C:/Users/bohda/Downloads/botContent.json")


class PosmatAIActionConfig(BaseConfig):
    """Environment-backed configuration for Posmat AI action runs."""

    def __init__(self, env_path: Optional[Path] = None) -> None:
        self.base_url: str = ""
        self.api_token: str = ""
        self.bot_public_id: str = ""
        self.request_timeout: int = DEFAULT_TIMEOUT
        self.bot_content_path: str = str(DEFAULT_BOT_CONTENT_PATH)
        super().__init__(env_path=env_path)

    def validate(self) -> None:
        self.base_url = str(self._get_env("BASE_URL", required=True)).strip().rstrip("/")
        self.api_token = str(self._get_env("API_TOKEN", required=True)).strip()
        self.bot_public_id = str(self._get_env("BOT_PUBLIC_ID", required=True)).strip()
        self.request_timeout = self._get_int_env("REQUEST_TIMEOUT", default=DEFAULT_TIMEOUT)
        self.bot_content_path = str(
            self._get_env("BOT_CONTENT_PATH", default=str(DEFAULT_BOT_CONTENT_PATH))
        ).strip()
