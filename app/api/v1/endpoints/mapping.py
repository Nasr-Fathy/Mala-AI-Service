from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_mapper_service
from app.core.config import Settings, get_settings
from app.core.tracing import build_trace_metadata
from app.schemas.mapping import MappingRequest, MappingResponse
from app.services.mapping.financial_mapper import FinancialMapperService

router = APIRouter(tags=["mapping"])


@router.post(
    "/mapping",
    response_model=MappingResponse,
    summary="Run multi-pass financial mapping on OCR data",
    description=(
        "Accepts structured OCR output and runs 4 LLM passes: "
        "metadata extraction, period detection, statement structuring "
        "(parallelised), and notes extraction."
    ),
)
async def run_mapping(
    body: MappingRequest,
    settings: Settings = Depends(get_settings),
    service: FinancialMapperService = Depends(get_mapper_service),
) -> MappingResponse:
    ocr_dict = body.ocr_data.model_dump()
    result = await service.process(
        ocr_dict,
        apply_categories=body.options.apply_category_mapping,
        langsmith_extra={
            "metadata": build_trace_metadata(
                environment=settings.ENVIRONMENT,
                endpoint="POST /api/v1/mapping",
                pipeline_type="financial",
            ),
            "tags": ["mapping", settings.ENVIRONMENT],
        },
    )
    return MappingResponse(
        pass_1_output=result["pass_1_output"],
        pass_2_output=result["pass_2_output"],
        pass_3_outputs=result["pass_3_outputs"],
        # pass_4_output=result["pass_4_output"],
        metadata=result.get("metadata", {}),
    )
