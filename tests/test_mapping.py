from __future__ import annotations

import pytest

from app.services.mapping.category_mapper import CategoryMapper
from app.services.mapping.financial_mapper import FinancialMapperService
from tests.conftest import FakeLLMClient


@pytest.mark.asyncio
async def test_mapper_runs_all_passes(fake_llm: FakeLLMClient, sample_capture_output: dict):
    """FinancialMapperService should invoke passes 1-4 and return combined output."""

    fake_llm.set_response("pass1_metadata", {
        "company": {"name_en": "Test Co"},
        "fiscal_periods": [{"fiscal_year": 2024, "period_type": "ANNUAL"}],
        "currency": {"code": "SAR"},
    })
    fake_llm.set_response("pass2_segmentation", {
        "statements": [
            {"statement_type": "BALANCE_SHEET", "start_page": 1, "end_page": 1, "table_ids": ["t1"], "columns": []}
        ],
        "notes_section": None,
    })
    fake_llm.set_response("pass3_BALANCE_SHEET", {
        "statement_type": "BALANCE_SHEET",
        "line_items": [{"name_en": "Cash", "values": [{"fiscal_year": 2024, "amount": 100}], "order": 0}],
        "totals": {},
        "confidence": 0.9,
    })

    cat = CategoryMapper()
    service = FinancialMapperService(fake_llm, cat)
    result = await service.process(sample_capture_output, apply_categories=False)

    assert "pass_1_output" in result
    assert "pass_2_output" in result
    assert "pass_3_outputs" in result
    assert "pass_4_output" in result
    assert result["pass_1_output"]["company"]["name_en"] == "Test Co"


def test_category_mapper_normalize():
    assert CategoryMapper.normalize("  Hello  World ") == "hello world"
    assert CategoryMapper.normalize("") == ""


def test_category_mapper_detect_language():
    assert CategoryMapper.detect_language("Hello") == "en"
    assert CategoryMapper.detect_language("مرحبا") == "ar"
    assert CategoryMapper.detect_language("") == "en"


def test_category_mapper_default_result():
    mapper = CategoryMapper()
    result = mapper.match("nonexistent item xyz")
    assert result["category"] == "OTHER"
    assert result["confidence"] == 0.0
