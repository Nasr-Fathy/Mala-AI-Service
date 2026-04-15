from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error envelope returned by all endpoints."""

    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ProcessingMetadata(BaseModel):
    """Metadata attached to every AI processing response."""

    model: str = ""
    prompt_version: str = ""
    processing_time_ms: int = 0
    attempt: int = 1
    estimated_tokens: int = 0


class HealthResponse(BaseModel):
    status: str
    version: str = ""
    environment: str = ""


class ReadinessResponse(BaseModel):
    status: str
    llm_status: str = ""
    model: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
