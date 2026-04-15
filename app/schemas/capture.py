from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ProcessingMetadata


class PageItem(BaseModel):
    page_number: int
    text: str
    original_page_number: int | None = None
    confidence: float | None = None


class TableItem(BaseModel):
    page: int
    table_id: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    original_page_number: int | None = None
    title: str | None = None


class CaptureResponse(BaseModel):
    """Response from ``POST /api/v1/capture``."""

    raw_text: str = ""
    pages: list[PageItem] = Field(default_factory=list)
    tables: list[TableItem] = Field(default_factory=list)
    detected_language: str | None = None
    page_map: dict[str, int] = Field(default_factory=dict)
    processed_pages: list[int] = Field(default_factory=list)
    page_count: int = 0
    is_schema_valid: bool = True
    schema_version: str = "v1"
    metadata: ProcessingMetadata = Field(default_factory=ProcessingMetadata)

    model_config = {"from_attributes": True}
