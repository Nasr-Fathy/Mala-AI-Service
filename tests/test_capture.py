from __future__ import annotations

import pytest

from app.services.capture.capture_service import CaptureService
from app.services.pdf.layout_service import LayoutService
from tests.conftest import FakeLLMClient


@pytest.mark.asyncio
async def test_capture_service_returns_valid_output(fake_llm: FakeLLMClient, sample_pdf_bytes: bytes):
    """CaptureService should call the LLM and return a well-shaped dict."""
    fake_llm.set_response("capture_ocr", {
        "raw_text": "Hello world",
        "pages": [{"page_number": 1, "text": "Hello world"}],
        "tables": [],
        "detected_language": "en",
    })

    service = CaptureService(fake_llm)
    result = await service.process(sample_pdf_bytes)

    assert result["is_schema_valid"] is True
    assert result["raw_text"] == "Hello world"
    assert len(result["pages"]) == 1
    assert result["pages"][0]["original_page_number"] == 1
    assert "metadata" in result


def test_layout_service_page_count(sample_pdf_bytes: bytes):
    count = LayoutService.get_page_count(sample_pdf_bytes)
    assert count == 1


def test_layout_service_build_page_map():
    pm = LayoutService.build_page_map([5, 6, 7])
    assert pm == {"0": 5, "1": 6, "2": 7}


def test_layout_service_validate_pdf(sample_pdf_bytes: bytes):
    info = LayoutService.validate_pdf(sample_pdf_bytes)
    assert info["is_valid"] is True
    assert info["page_count"] == 1


def test_layout_service_validate_invalid_pdf():
    info = LayoutService.validate_pdf(b"not a pdf")
    assert info["is_valid"] is False
