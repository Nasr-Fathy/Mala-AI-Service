from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OCRData(BaseModel):
    """OCR output that feeds into the mapping stage."""

    raw_text: str = ""
    pages: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    detected_language: str | None = None


class MappingOptions(BaseModel):
    apply_category_mapping: bool = True
    parallel_pass3: bool = True


class MappingRequest(BaseModel):
    """Request body for ``POST /api/v1/mapping``."""

    ocr_data: OCRData
    options: MappingOptions = Field(default_factory=MappingOptions)


class MappingMetadata(BaseModel):
    model: str = ""
    prompt_version: str = ""
    processing_time_ms: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0


class MappingResponse(BaseModel):
    """Response from ``POST /api/v1/mapping``."""

    pass_1_output: dict[str, Any] = Field(default_factory=dict)
    pass_2_output: dict[str, Any] = Field(default_factory=dict)
    pass_3_outputs: dict[str, Any] = Field(default_factory=dict)
    pass_4_output: dict[str, Any] = Field(default_factory=dict)
    metadata: MappingMetadata = Field(default_factory=MappingMetadata)

    model_config = {"from_attributes": True}
