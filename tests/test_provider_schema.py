from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.exceptions import SchemaValidationError
from app.services.capture.capture_service import CaptureService
from app.services.llm.provider_schema import ProviderOutputNormalizer, ProviderSchemaAdapter
from app.validation.schema_validator import SchemaValidator
from tests.conftest import FakeLLMClient


def _sample_nullable_schema() -> dict:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "value": {"type": ["string", "null"]},
            "rows": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": ["string", "number", "null"]},
                },
            },
        },
    }


def test_vertex_schema_adapter_keeps_original_immutable():
    canonical = _sample_nullable_schema()
    canonical_before = deepcopy(canonical)

    adapted = ProviderSchemaAdapter.for_provider(canonical, "vertex")

    assert canonical == canonical_before
    assert "$schema" in canonical
    assert "$schema" not in adapted


def test_vertex_schema_adapter_adapts_null_unions():
    canonical = _sample_nullable_schema()
    adapted = ProviderSchemaAdapter.for_provider(canonical, "vertex")

    assert adapted["properties"]["value"]["type"] == "string"
    row_items = adapted["properties"]["rows"]["items"]["items"]
    assert "type" not in row_items
    assert row_items["anyOf"] == [{"type": "string"}, {"type": "number"}]


def test_vertex_output_normalizer_restores_null_semantics():
    schema = _sample_nullable_schema()
    data = {"value": "", "rows": [["-", "null", 10]]}

    normalized = ProviderOutputNormalizer.normalize("vertex", data, schema)

    assert normalized["value"] is None
    assert normalized["rows"][0][0] is None
    assert normalized["rows"][0][1] is None
    assert normalized["rows"][0][2] == 10


@pytest.mark.asyncio
async def test_capture_pipeline_uses_provider_schema_and_validates(sample_pdf_bytes: bytes):
    llm = FakeLLMClient()
    llm.set_response(
        "capture_ocr",
        {
            "raw_text": "text",
            "pages": [{"page_number": 1, "text": "text"}],
            "tables": [
                {"page": 1, "table_id": "t1", "headers": ["h1"], "rows": [["null", ""]]},
            ],
            "detected_language": "en",
        },
    )

    service = CaptureService(llm)
    result = await service.process(sample_pdf_bytes)

    call = llm.calls[-1]
    assert call["method"] == "generate_from_pdf"
    assert isinstance(call["response_schema"], dict)
    assert "$schema" not in call["response_schema"]
    assert result["tables"][0]["rows"][0][0] is None
    assert result["tables"][0]["rows"][0][1] is None

    # Ensure final object still validates against canonical schema semantics.
    canonical = SchemaValidator.load_raw_schema("capture_output")
    ok, errors = SchemaValidator.validate_against_schema(
        canonical,
        {
            "raw_text": result["raw_text"],
            "pages": result["pages"],
            "tables": result["tables"],
            "detected_language": result["detected_language"],
        },
    )
    assert ok, errors


@pytest.mark.asyncio
async def test_capture_pipeline_still_fails_canonical_validation(sample_pdf_bytes: bytes):
    llm = FakeLLMClient()
    llm.set_response(
        "capture_ocr",
        {
            # Invalid canonical payload: missing required "raw_text"
            "pages": [{"page_number": 1, "text": "text"}],
            "tables": [],
        },
    )
    service = CaptureService(llm)

    with pytest.raises(SchemaValidationError):
        await service.process(sample_pdf_bytes)
