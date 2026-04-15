from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_capture_service
from app.core.config import Settings, get_settings
from app.core.exceptions import PDFError
from app.core.tracing import build_trace_metadata
from app.schemas.capture import CaptureResponse
from app.services.capture.capture_service import CaptureService

router = APIRouter(tags=["capture"])


@router.post(
    "/capture",
    response_model=CaptureResponse,
    summary="Extract text and tables from a PDF via OCR",
    description=(
        "Accepts a PDF file upload, runs Vertex AI OCR, validates the output "
        "against the capture schema, maps pages to originals, and returns "
        "structured data."
    ),
)
async def run_capture(
    file: UploadFile = File(..., description="PDF document to process"),
    page_numbers: str | None = Form(None, description="JSON array of 1-indexed page numbers"),
    settings: Settings = Depends(get_settings),
    service: CaptureService = Depends(get_capture_service),
) -> CaptureResponse:
    pdf_bytes = await file.read()

    if len(pdf_bytes) > settings.max_upload_bytes:
        raise PDFError(f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB")

    pages: list[int] | None = None
    if page_numbers:
        try:
            pages = json.loads(page_numbers)
        except (json.JSONDecodeError, TypeError) as e:
            raise PDFError(
                f"Invalid page_numbers format: {e}. Expected a JSON array like [1,2,3]."
            ) from e
        if not isinstance(pages, list) or not all(isinstance(p, int) for p in pages):
            raise PDFError("page_numbers must be a JSON array of integers, e.g. [1,2,3].")

    result = await service.process(
        pdf_bytes,
        pages,
        langsmith_extra={
            "metadata": build_trace_metadata(
                environment=settings.ENVIRONMENT,
                endpoint="POST /api/v1/capture",
                file_name=file.filename or "unknown",
                file_size_bytes=len(pdf_bytes),
                page_numbers=pages,
            ),
            "tags": ["capture", settings.ENVIRONMENT],
        },
    )
    return CaptureResponse(**result)
