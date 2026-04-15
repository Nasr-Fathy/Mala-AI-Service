from __future__ import annotations

import time
from typing import Any

from langsmith import traceable

from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs
from app.pipeline.base_step import BasePipelineStep, PipelineContext, StepResult
from app.services.capture.capture_service import CaptureService

logger = get_logger(__name__)


class CaptureStep(BasePipelineStep):
    """Pipeline step wrapping :class:`CaptureService`."""

    name = "capture"

    def __init__(self, capture_service: CaptureService) -> None:
        self._service = capture_service

    async def validate_input(self, context: PipelineContext) -> bool:
        pdf = context.get("pdf_bytes")
        if not pdf or not isinstance(pdf, bytes):
            logger.error("capture_step_missing_pdf")
            return False
        return True

    @traceable(run_type="chain", name="capture_step", process_inputs=filter_trace_inputs)
    async def execute(self, context: PipelineContext) -> StepResult:
        pdf_bytes: bytes = context.get("pdf_bytes")
        page_numbers: list[int] | None = context.get("page_numbers")

        start = time.time()
        try:
            output = await self._service.process(pdf_bytes, page_numbers)
            context.set("capture_output", output)
            return StepResult(success=True, output=output, elapsed_ms=int((time.time() - start) * 1000))
        except Exception as e:
            logger.error(
                "capture_step_failed",
                exc_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return StepResult(success=False, error=str(e), elapsed_ms=int((time.time() - start) * 1000))
