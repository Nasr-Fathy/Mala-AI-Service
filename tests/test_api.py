from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_endpoint(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_capture_endpoint(async_client: AsyncClient, fake_llm, sample_pdf_bytes: bytes):
    fake_llm.set_response("capture_ocr", {
        "raw_text": "Test text",
        "pages": [{"page_number": 1, "text": "Test text"}],
        "tables": [],
        "detected_language": "en",
    })

    resp = await async_client.post(
        "/api/v1/capture",
        files={"file": ("test.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_text"] == "Test text"
    assert data["is_schema_valid"] is True


@pytest.mark.asyncio
async def test_mapping_endpoint(async_client: AsyncClient, fake_llm, sample_capture_output: dict):
    fake_llm.set_response("pass1_metadata", {
        "company": {"name_en": "Co"},
        "fiscal_periods": [{"fiscal_year": 2024, "period_type": "ANNUAL"}],
        "currency": {"code": "SAR"},
    })
    fake_llm.set_response("pass2_segmentation", {
        "statements": [],
        "notes_section": None,
    })

    body = {
        "ocr_data": {
            "raw_text": sample_capture_output["raw_text"],
            "pages": sample_capture_output["pages"],
            "tables": sample_capture_output["tables"],
            "detected_language": "en",
        },
    }
    resp = await async_client.post("/api/v1/mapping", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert "pass_1_output" in data
    assert data["pass_1_output"]["company"]["name_en"] == "Co"
