"""Base configuration helpers for Posmat automation."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

from dotenv import load_dotenv


class BaseConfig(ABC):
    """Abstract base class for environment-backed configuration."""

    def __init__(self, env_path: Optional[Union[str, Path]] = None) -> None:
        if env_path is not None:
            load_dotenv(Path(env_path))
        else:
            load_dotenv()
        self.validate()

    def _get_env(
        self,
        key: str,
        default: Optional[Any] = None,
        *,
        required: bool = False,
    ) -> Any:
        value = os.getenv(key, default)
        if required and (value is None or str(value).strip() == ""):
            raise ValueError(
                f"Required environment variable '{key}' not found. "
                "Please set it in your .env file."
            )
        return value

    def _get_int_env(self, key: str, default: int) -> int:
        value = os.getenv(key)
        if value is None or str(value).strip() == "":
            return default
        try:
            return int(value)
        except ValueError:
            return default

    @abstractmethod
    def validate(self) -> None:
        """Validate the current configuration."""
