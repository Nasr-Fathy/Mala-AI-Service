"""Tests for token usage normalization, cost, and LangSmith metadata helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm.llm_finalize import (
    build_langsmith_usage_metadata,
    supplement_missing_token_estimates,
)
from app.services.llm.billing_calculator import compute_billing
from app.services.llm.pricing_registry import calculate_cost, resolve_pricing
from app.services.llm.token_usage import TokenUsage
from app.services.llm.usage_normalize import (
    normalize_openai_response,
    normalize_usage,
    normalize_vertex_response,
)


def test_normalize_vertex_gemini_usage():
    um = SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=50,
        total_token_count=150,
        cached_content_token_count=10,
        thoughts_token_count=None,
    )
    resp = SimpleNamespace(usage_metadata=um)
    u = normalize_vertex_response("gemini-1.5-pro-002", resp)
    assert u.provider == "vertex"
    assert u.input_tokens == 100
    assert u.output_tokens == 50
    assert u.total_tokens == 150
    assert u.cached_tokens == 10
    assert u.inferred_extra_tokens == 0
    assert u.raw_usage is not None


def test_normalize_vertex_gemini_inferred_extra_from_metadata():
    um = SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=50,
        total_token_count=200,
        cached_content_token_count=None,
        thoughts_token_count=None,
    )
    resp = SimpleNamespace(usage_metadata=um)
    u = normalize_vertex_response("gemini-1.5-pro-002", resp)
    assert u.inferred_extra_tokens == 50


def test_normalize_openai_usage():
    usage_obj = SimpleNamespace(
        prompt_tokens=20,
        completion_tokens=10,
        total_tokens=30,
        prompt_tokens_details=None,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
    )
    resp = SimpleNamespace(usage=usage_obj, model="gpt-4o-mini")
    u = normalize_openai_response("gpt-4o-mini", resp)
    assert u.provider == "openai"
    assert u.input_tokens == 20
    assert u.output_tokens == 10
    assert u.total_tokens == 30
    assert u.reasoning_tokens == 3


def test_normalize_openai_reasoning_in_dict():
    usage_obj = SimpleNamespace(
        prompt_tokens=1,
        completion_tokens=5,
        total_tokens=6,
        prompt_tokens_details=None,
        completion_tokens_details={"reasoning_tokens": 2},
    )
    resp = SimpleNamespace(usage=usage_obj, model="o3")
    u = normalize_openai_response("o3", resp)
    assert u.reasoning_tokens == 2


def test_normalize_usage_dispatch():
    v = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=1,
            candidates_token_count=2,
            total_token_count=3,
            cached_content_token_count=None,
            thoughts_token_count=None,
        )
    )
    u = normalize_usage("vertex", "gemini-1.5-pro-002", v)
    assert u.input_tokens == 1


def test_missing_usage_fields_vertex():
    resp = SimpleNamespace(usage_metadata=None)
    u = normalize_vertex_response("gemini-1.5-pro-002", resp)
    assert u.input_tokens is None
    assert u.output_tokens is None
    assert u.total_tokens is None


def test_supplement_fills_estimates():
    u = TokenUsage(provider="vertex", model_name="x")
    u2 = supplement_missing_token_estimates(
        u,
        content_parts=["abcd"],
        raw_text="abcdefgh",
    )
    assert u2.input_tokens == 1  # len//4
    assert u2.output_tokens == 2
    assert u2.total_tokens == 3


def test_supplement_gemini_partial_without_total_does_not_use_p_plus_c():
    """API returned prompt + candidates but not total: do not infer total as P+C."""
    u = TokenUsage(
        provider="vertex",
        model_name="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=50,
        total_tokens=None,
    )
    u2 = supplement_missing_token_estimates(
        u,
        content_parts=None,
        raw_text="",
    )
    assert u2.input_tokens == 100
    assert u2.output_tokens == 50
    assert u2.total_tokens is None


def test_coalesce_total_tokens_gemini_returns_none_without_api_total():
    from app.services.llm.token_usage import coalesce_total_tokens

    u = TokenUsage(
        provider="vertex",
        model_name="m",
        input_tokens=10,
        output_tokens=20,
        total_tokens=None,
    )
    assert coalesce_total_tokens(u) is None


def test_build_langsmith_usage_metadata_includes_billing_in_usage_metadata():
    from app.services.llm.billing_types import BillingBreakdown

    bd = BillingBreakdown(
        inferred_extra_tokens=10,
        billable_input_tokens=5,
        billable_cached_input_tokens=2,
        billable_output_tokens=3,
        billable_reasoning_tokens=0,
        billable_other_tokens=10,
        cost_input=0.01,
        cost_cached_input=0.002,
        cost_output=0.03,
        cost_reasoning=None,
        cost_other=0.05,
        cost_total=0.092,
    )
    u = TokenUsage(
        input_tokens=10,
        output_tokens=3,
        total_tokens=30,
        provider="vertex",
        model_name="gemini-1.5-pro-002",
        billing=bd,
        raw_usage={"prompt_token_count": 10},
    )
    m = build_langsmith_usage_metadata(u)
    assert m["raw_usage"] == {"prompt_token_count": 10}
    assert m["billing_breakdown"]["billable_other_tokens"] == 10
    um = m["usage_metadata"]
    assert um["billable_input_tokens"] == 5
    assert um["cost_total_usd"] == 0.092


def test_cost_calculation_known_model():
    u = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        total_tokens=2_000_000,
        provider="openai",
        model_name="gpt-4o-mini",
    )
    priced = calculate_cost("openai", "gpt-4o-mini", u)
    assert priced.cost_input is not None
    assert priced.cost_output is not None
    assert priced.cost_total is not None
    assert abs(priced.cost_input - 0.15) < 1e-9
    assert abs(priced.cost_output - 0.60) < 1e-9


def test_cost_unknown_model_returns_none():
    u = TokenUsage(
        input_tokens=100,
        output_tokens=100,
        total_tokens=200,
        provider="openai",
        model_name="unknown-model-xyz",
    )
    priced = calculate_cost("openai", "unknown-model-xyz", u)
    assert priced.cost_input is None
    assert priced.cost_output is None
    assert priced.cost_total is None


def test_resolve_pricing_alias():
    p = resolve_pricing("vertex", "gemini-1.5-pro-latest")
    assert p is not None


def test_build_langsmith_usage_metadata():
    u = TokenUsage(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        reasoning_tokens=None,
        cached_tokens=None,
        provider="openai",
        model_name="gpt-4o",
        cost_input=0.1,
        cost_output=0.2,
        cost_total=0.3,
        raw_usage={"prompt_tokens": 1},
    )
    m = build_langsmith_usage_metadata(u)
    assert m["ls_provider"] == "openai"
    assert m["ls_model_name"] == "gpt-4o"
    assert m["usage_metadata"]["input_tokens"] == 1
    assert m["usage_metadata"]["total_tokens"] == 3
    assert m["cost_total_usd"] == 0.3
    assert m["raw_usage"] == {"prompt_tokens": 1}


def test_gemini_reasoning_mode_uses_reasoning_tokens_bucket():
    """If reasoning mode is enabled, reasoning_tokens are billed as reasoning."""
    from app.services.llm import pricing_registry as pr
    from app.services.llm.billing_types import ModelBillingConfig

    model = "gemini-test-reasoning-mode"
    pr._PRICING[("vertex", model)] = pr.ModelPricing(
        input_price_per_million=1.0,
        output_price_per_million=2.0,
        cached_input_price_per_million=0.5,
        reasoning_price_per_million=3.0,
        other_price_per_million=4.0,
    )
    pr._BILLING_CONFIG[("vertex", model)] = ModelBillingConfig(
        cached_tokens_included_in_input=True,
        use_total_as_billed_truth=False,
        extra_tokens_are_reasoning=True,
        fallback_bill_extra_as_output=False,
    )
    try:
        u = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=500,
            cached_tokens=0,
            reasoning_tokens=120,
            provider="vertex",
            model_name=model,
        )
        out = compute_billing("vertex", model, u)
        assert out.billing is not None
        assert out.billing.inferred_extra_tokens == 350
        assert out.billing.billable_reasoning_tokens == 120
        assert out.billing.billable_other_tokens == 0
    finally:
        pr._PRICING.pop(("vertex", model), None)
        pr._BILLING_CONFIG.pop(("vertex", model), None)


def test_gemini_example_1_fallback_extra_as_output_price():
    """Matches provided example where extra is billed in other bucket at output rate fallback."""
    from app.services.llm import pricing_registry as pr
    from app.services.llm.billing_types import ModelBillingConfig

    model = "gemini-test-example-1"
    pr._PRICING[("vertex", model)] = pr.ModelPricing(
        input_price_per_million=0.20,
        output_price_per_million=2.9724604966,
        cached_input_price_per_million=0.05,
        reasoning_price_per_million=None,
        other_price_per_million=None,
    )
    pr._BILLING_CONFIG[("vertex", model)] = ModelBillingConfig(
        cached_tokens_included_in_input=True,
        use_total_as_billed_truth=False,
        extra_tokens_are_reasoning=False,
        fallback_bill_extra_as_output=True,
    )
    try:
        u = TokenUsage(
            input_tokens=1482,
            output_tokens=2215,
            total_tokens=9712,
            cached_tokens=0,
            reasoning_tokens=None,
            provider="vertex",
            model_name=model,
        )
        out = compute_billing("vertex", model, u)
        assert out.billing is not None
        assert out.billing.inferred_extra_tokens == 6015
        assert out.billing.billable_other_tokens == 6015
        assert out.billing.billable_output_tokens == 2215
        assert out.billing.cost_input == pytest.approx(0.0002964, abs=1e-10)
        assert out.billing.cost_output == pytest.approx(0.006584, abs=1e-6)
        assert out.billing.cost_other == pytest.approx(0.01788, abs=1e-5)
        assert out.billing.cost_total == pytest.approx(0.0247604, abs=1e-6)
    finally:
        pr._PRICING.pop(("vertex", model), None)
        pr._BILLING_CONFIG.pop(("vertex", model), None)


def test_gemini_example_2_cached_and_extra_buckets():
    """Matches provided example where cached input and inferred extra are billed separately."""
    from app.services.llm import pricing_registry as pr
    from app.services.llm.billing_types import ModelBillingConfig

    model = "gemini-test-example-2"
    pr._PRICING[("vertex", model)] = pr.ModelPricing(
        input_price_per_million=0.20,
        output_price_per_million=0.80,
        cached_input_price_per_million=0.05,
        reasoning_price_per_million=None,
        other_price_per_million=0.80,
    )
    pr._BILLING_CONFIG[("vertex", model)] = ModelBillingConfig(
        cached_tokens_included_in_input=True,
        use_total_as_billed_truth=False,
        extra_tokens_are_reasoning=False,
        fallback_bill_extra_as_output=False,
    )
    try:
        u = TokenUsage(
            input_tokens=4297,
            output_tokens=5145,
            total_tokens=21737,
            cached_tokens=4014,
            reasoning_tokens=None,
            provider="vertex",
            model_name=model,
        )
        out = compute_billing("vertex", model, u)
        assert out.billing is not None
        assert out.billing.inferred_extra_tokens == 12295
        assert out.billing.billable_input_tokens == 283
        assert out.billing.billable_cached_input_tokens == 4014
        assert out.billing.billable_output_tokens == 5145
        assert out.billing.billable_other_tokens == 12295
        assert out.billing.cost_input == pytest.approx(0.0000566, abs=1e-10)
        assert out.billing.cost_cached_input == pytest.approx(0.0002007, abs=1e-10)
        assert out.billing.cost_output == pytest.approx(0.004116, abs=1e-9)
        assert out.billing.cost_other == pytest.approx(0.009836, abs=1e-9)
        assert out.billing.cost_total == pytest.approx(0.0142093, abs=1e-9)
    finally:
        pr._PRICING.pop(("vertex", model), None)
        pr._BILLING_CONFIG.pop(("vertex", model), None)


def test_gemini_inferred_extra_and_billable_buckets():
    """Observed-style Gemini usage: gap T-P-C must not be ignored in billing."""
    u = TokenUsage(
        input_tokens=4297,
        output_tokens=5145,
        total_tokens=21737,
        cached_tokens=4014,
        reasoning_tokens=None,
        provider="vertex",
        model_name="gemini-1.5-pro-002",
    )
    out = compute_billing("vertex", "gemini-1.5-pro-002", u)
    assert out.billing is not None
    assert out.inferred_extra_tokens == 12295
    assert out.billing.billable_input_tokens == 283
    assert out.billing.billable_cached_input_tokens == 4014
    assert out.billing.billable_output_tokens == 5145
    assert out.billing.billable_other_tokens == 12295
    assert out.billing.cost_other is not None
    naive = (4297 / 1e6) * 1.25 + (5145 / 1e6) * 5.0
    assert out.billing.cost_total is not None
    assert out.billing.cost_total > naive


def test_compute_billing_equals_calculate_cost_alias():
    u = TokenUsage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        provider="openai",
        model_name="gpt-4o-mini",
    )
    a = calculate_cost("openai", "gpt-4o-mini", u)
    b = compute_billing("openai", "gpt-4o-mini", u)
    assert a.cost_total == b.cost_total
    assert a.billing is not None and b.billing is not None


def test_gemini_cached_price_fallback_logs(caplog):
    """When cached_input_price is missing, fallback uses input price and notes."""
    import logging

    from app.services.llm import pricing_registry as pr

    u = TokenUsage(
        input_tokens=100,
        output_tokens=10,
        total_tokens=120,
        cached_tokens=40,
        provider="vertex",
        model_name="gemini-1.5-pro-002",
    )
    orig = pr._PRICING.get(("vertex", "gemini-1.5-pro-002"))
    assert orig is not None
    patched = pr.ModelPricing(
        input_price_per_million=orig.input_price_per_million,
        output_price_per_million=orig.output_price_per_million,
        cached_input_price_per_million=None,
        reasoning_price_per_million=orig.reasoning_price_per_million,
        other_price_per_million=orig.other_price_per_million,
    )
    pr._PRICING[("vertex", "gemini-1.5-pro-002")] = patched
    try:
        with caplog.at_level(logging.WARNING):
            out = compute_billing("vertex", "gemini-1.5-pro-002", u)
        assert "llm_cached_price_fallback" in caplog.text or any(
            "cached_input_used_input_price_assumption" in n for n in (out.billing.billing_notes if out.billing else [])
        )
        assert out.billing is not None
        assert out.billing.cost_cached_input is not None
    finally:
        pr._PRICING[("vertex", "gemini-1.5-pro-002")] = orig
