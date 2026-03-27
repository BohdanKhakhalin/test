"""Base evaluator contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseEvaluator(ABC):
    """Abstract evaluator interface."""

    @abstractmethod
    def evaluate(self, test_input: Any, **kwargs: Any) -> Any:
        """Evaluate one input and return a result record."""
