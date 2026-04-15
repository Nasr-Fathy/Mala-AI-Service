from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    """Optional config passed when triggering the full pipeline."""

    page_numbers: list[int] | None = None
    apply_category_mapping: bool = True


class PipelineStepSummary(BaseModel):
    step: str
    success: bool
    elapsed_ms: int = 0
    error: str | None = None


class PipelineMetadata(BaseModel):
    steps: list[PipelineStepSummary] = Field(default_factory=list)
    total_elapsed_ms: int = 0


class PipelineResponse(BaseModel):
    """Response from ``POST /api/v1/pipeline/execute``."""

    capture_output: dict[str, Any] = Field(default_factory=dict)
    mapping_output: dict[str, Any] = Field(default_factory=dict)
    pipeline_metadata: PipelineMetadata = Field(default_factory=PipelineMetadata)

    model_config = {"from_attributes": True}
