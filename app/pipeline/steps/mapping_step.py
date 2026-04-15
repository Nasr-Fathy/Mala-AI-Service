from __future__ import annotations

import time

from langsmith import traceable

from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs
from app.pipeline.base_step import BasePipelineStep, PipelineContext, StepResult
from app.services.mapping.financial_mapper import FinancialMapperService

logger = get_logger(__name__)


class MappingStep(BasePipelineStep):
    """Pipeline step wrapping :class:`FinancialMapperService`."""

    name = "mapping"

    def __init__(self, mapper_service: FinancialMapperService) -> None:
        self._service = mapper_service

    async def validate_input(self, context: PipelineContext) -> bool:
        capture = context.get("capture_output")
        if not capture or not isinstance(capture, dict):
            logger.error("mapping_step_missing_capture")
            return False
        if not capture.get("raw_text") and not capture.get("pages"):
            logger.error("mapping_step_empty_capture")
            return False
        return True

    @traceable(run_type="chain", name="mapping_step", process_inputs=filter_trace_inputs)
    async def execute(self, context: PipelineContext) -> StepResult:
        capture_output: dict = context.get("capture_output")
        apply_cats = context.get("apply_category_mapping", True)

        start = time.time()
        try:
            output = await self._service.process(capture_output, apply_categories=apply_cats)
            context.set("mapping_output", output)
            return StepResult(success=True, output=output, elapsed_ms=int((time.time() - start) * 1000))
        except Exception as e:
            logger.error(
                "mapping_step_failed",
                exc_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return StepResult(success=False, error=str(e), elapsed_ms=int((time.time() - start) * 1000))
