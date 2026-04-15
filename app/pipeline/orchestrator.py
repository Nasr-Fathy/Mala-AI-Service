from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from langsmith import traceable

from app.core.exceptions import PipelineError, StepError
from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs, filter_trace_outputs
from app.pipeline.base_step import PipelineContext, StepResult
from app.pipeline.registry import StepRegistry

EXPERIMENT_DIR = Path(__file__).resolve().parents[2] / "experment"

logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    Executes registered pipeline steps **sequentially**.

    The orchestrator is intentionally simple:
      - iterate over the registry's ordered steps
      - validate inputs, execute, record results
      - stop on first failure
    """

    def __init__(self, registry: StepRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _dump_step_output(step_name: str, output: dict[str, Any]) -> None:
        """Persist a step's output as a JSON file for experimentation."""
        try:
            EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
            dest = EXPERIMENT_DIR / f"{step_name}.json"
            dest.write_text(
                json.dumps(output, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("step_output_saved", step=step_name, path=str(dest))
        except Exception as exc:
            logger.warning("step_output_save_failed", step=step_name, error=str(exc))

    @traceable(
        run_type="chain",
        name="pipeline_execution",
        process_inputs=filter_trace_inputs,
        process_outputs=filter_trace_outputs,
    )
    async def run(self, initial_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute the full pipeline.

        Args:
            initial_data: Seed data placed into the context before execution
                          (e.g. ``pdf_bytes``, ``page_numbers``).

        Returns:
            Combined results from all steps plus overall metadata.
        """
        ctx = PipelineContext(data=dict(initial_data or {}))
        steps = self._registry.ordered_steps
        step_results: list[dict[str, Any]] = []
        overall_start = time.time()

        logger.info("pipeline_start", steps=[s.name for s in steps])

        for step in steps:
            step_start = time.time()
            logger.info("step_start", step=step.name)

            if not await step.validate_input(ctx):
                error_msg = f"Input validation failed for step '{step.name}'"
                logger.error("step_validation_failed", step=step.name, context_keys=list(ctx.data.keys()))
                raise StepError(step.name, error_msg)

            try:
                result: StepResult = await step.execute(ctx)
            except StepError:
                logger.error("step_execution_error", step=step.name, exc_info=True)
                raise
            except Exception as e:
                logger.error(
                    "step_execution_error",
                    step=step.name,
                    exc_type=type(e).__name__,
                    error=str(e),
                    exc_info=True,
                )
                raise StepError(step.name, str(e)) from e

            elapsed = int((time.time() - step_start) * 1000)
            result.elapsed_ms = elapsed

            step_results.append({
                "step": step.name,
                "success": result.success,
                "elapsed_ms": elapsed,
                "error": result.error,
            })

            if not result.success:
                logger.error(
                    "step_failed",
                    step=step.name,
                    error=result.error,
                    elapsed_ms=elapsed,
                )
                raise StepError(step.name, result.error or "Unknown error")

            self._dump_step_output(step.name, result.output)
            logger.info("step_complete", step=step.name, elapsed_ms=elapsed)

        overall_elapsed = int((time.time() - overall_start) * 1000)
        logger.info("pipeline_complete", elapsed_ms=overall_elapsed)

        return {
            **ctx.data,
            "_pipeline_metadata": {
                "steps": step_results,
                "total_elapsed_ms": overall_elapsed,
            },
        }
