from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError

from app.api.deps import get_pipeline
from app.core.config import Settings, get_settings
from app.core.exceptions import PDFError, PipelineError
from app.core.tracing import build_trace_metadata
from app.pipeline.orchestrator import PipelineOrchestrator
from app.schemas.pipeline import PipelineConfig, PipelineResponse

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post(
    "/execute",
    response_model=PipelineResponse,
    summary="Run the full AI pipeline (capture + mapping)",
    description=(
        "Accepts a PDF and optional configuration, then runs the complete "
        "AI pipeline: OCR data capture followed by financial mapping."
    ),
)
async def execute_pipeline(
    file: UploadFile = File(..., description="PDF document to process"),
    config: str | None = Form(None, description="JSON pipeline configuration"),
    settings: Settings = Depends(get_settings),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> PipelineResponse:
    pdf_bytes = await file.read()

    if len(pdf_bytes) > settings.max_upload_bytes:
        raise PDFError(f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB")

    cfg = PipelineConfig()
    if config:
        try:
            cfg = PipelineConfig(**json.loads(config))
        except json.JSONDecodeError as e:
            raise PipelineError(f"Invalid config JSON: {e}") from e
        except ValidationError as e:
            raise PipelineError(f"Invalid pipeline config: {e}") from e

    initial_data = {
        "pdf_bytes": pdf_bytes,
        "page_numbers": cfg.page_numbers,
        "apply_category_mapping": cfg.apply_category_mapping,
    }

    result = await pipeline.run(
        initial_data,
        langsmith_extra={
            "metadata": build_trace_metadata(
                environment=settings.ENVIRONMENT,
                endpoint="POST /api/v1/pipeline/execute",
                pipeline_type="financial",
                file_name=file.filename or "unknown",
                file_size_bytes=len(pdf_bytes),
                page_numbers=cfg.page_numbers,
            ),
            "tags": ["pipeline", settings.ENVIRONMENT],
        },
    )

    pipeline_meta = result.get("_pipeline_metadata", {})

    return PipelineResponse(
        capture_output=result.get("capture_output", {}),
        mapping_output=result.get("mapping_output", {}),
        pipeline_metadata=pipeline_meta,
    )
