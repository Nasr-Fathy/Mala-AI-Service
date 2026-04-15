from __future__ import annotations

from app.core.logging import get_logger
from app.pipeline.base_step import BasePipelineStep

logger = get_logger(__name__)


class StepRegistry:
    """
    Registry of available pipeline steps.

    Steps are stored **in insertion order** and executed sequentially.
    Extending the pipeline with new AI stages is a matter of:
      1. implement ``BasePipelineStep``
      2. call ``registry.register(step)``
    """

    def __init__(self) -> None:
        self._steps: dict[str, BasePipelineStep] = {}

    def register(self, step: BasePipelineStep) -> None:
        if step.name in self._steps:
            logger.warning("step_already_registered", step=step.name)
        self._steps[step.name] = step
        logger.info("step_registered", step=step.name)

    def get(self, name: str) -> BasePipelineStep | None:
        return self._steps.get(name)

    @property
    def ordered_steps(self) -> list[BasePipelineStep]:
        return list(self._steps.values())

    @property
    def step_names(self) -> list[str]:
        return list(self._steps.keys())

    def __len__(self) -> int:
        return len(self._steps)
