from __future__ import annotations

import pytest

from app.pipeline.base_step import BasePipelineStep, PipelineContext, StepResult
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.registry import StepRegistry
from app.core.exceptions import StepError


class PassStep(BasePipelineStep):
    name = "pass_step"

    async def validate_input(self, ctx: PipelineContext) -> bool:
        return True

    async def execute(self, ctx: PipelineContext) -> StepResult:
        ctx.set("pass_done", True)
        return StepResult(success=True, output={"done": True})


class FailStep(BasePipelineStep):
    name = "fail_step"

    async def validate_input(self, ctx: PipelineContext) -> bool:
        return True

    async def execute(self, ctx: PipelineContext) -> StepResult:
        return StepResult(success=False, error="intentional failure")


class ValidationFailStep(BasePipelineStep):
    name = "val_fail"

    async def validate_input(self, ctx: PipelineContext) -> bool:
        return False

    async def execute(self, ctx: PipelineContext) -> StepResult:
        return StepResult(success=True)


@pytest.mark.asyncio
async def test_orchestrator_runs_steps():
    reg = StepRegistry()
    reg.register(PassStep())
    orch = PipelineOrchestrator(reg)

    result = await orch.run({"seed": 1})

    assert result["pass_done"] is True
    assert "_pipeline_metadata" in result
    steps = result["_pipeline_metadata"]["steps"]
    assert len(steps) == 1
    assert steps[0]["success"] is True


@pytest.mark.asyncio
async def test_orchestrator_stops_on_failure():
    reg = StepRegistry()
    reg.register(FailStep())
    reg.register(PassStep())
    orch = PipelineOrchestrator(reg)

    with pytest.raises(StepError):
        await orch.run()


@pytest.mark.asyncio
async def test_orchestrator_validation_failure():
    reg = StepRegistry()
    reg.register(ValidationFailStep())
    orch = PipelineOrchestrator(reg)

    with pytest.raises(StepError):
        await orch.run()


def test_registry_ordering():
    reg = StepRegistry()
    reg.register(PassStep())
    f = FailStep()
    f.name = "second"
    reg.register(f)
    assert reg.step_names == ["pass_step", "second"]
    assert len(reg) == 2
