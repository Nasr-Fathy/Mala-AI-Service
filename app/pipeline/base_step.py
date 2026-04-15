from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineContext:
    """
    Mutable bag carried through every pipeline step.

    Steps read their inputs from *data* and write their outputs back into it
    so downstream steps can consume them.
    """

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class StepResult:
    """Outcome of a single pipeline step."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: int = 0


class BasePipelineStep(ABC):
    """
    Interface for a single step in the AI pipeline.

    Each step:
      1. validates its required inputs from context
      2. runs its logic
      3. writes its results back to context
    """

    name: str = "base"

    @abstractmethod
    async def execute(self, context: PipelineContext) -> StepResult:
        """Run the step logic."""

    @abstractmethod
    async def validate_input(self, context: PipelineContext) -> bool:
        """Return True if the required inputs are present in *context*."""
