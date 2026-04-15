"""Per-provider, per-model pricing (USD per 1M tokens).

Assumptions used in this registry:
- Google Gemini Developer API (provider: "google_genai"):
  use current public "Standard" pricing for <= 200K prompt context.
- Google Vertex AI (provider: "vertex"):
  use current public "Standard" pricing for <= 200K prompt context.
- OpenAI (provider: "openai"):
  use current public standard per-1M token pricing.
- "other_price_per_million" defaults to output pricing where inferred extra tokens
  are billed like output/reasoning tokens.
- Older Gemini 1.5 entries are kept as legacy placeholders because current public
  Google pricing pages no longer expose them in the same per-1M-token table format.

If you need:
- long-context rates (> 200K)
- batch/flex/priority specific pricing
- contract-specific discounts
then model this in a richer pricing layer instead of a single flat rate entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.llm.billing_types import ModelBillingConfig
from app.services.llm.token_usage import TokenUsage

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens."""

    input_price_per_million: float
    output_price_per_million: float
    cached_input_price_per_million: float | None = None
    reasoning_price_per_million: float | None = None
    other_price_per_million: float | None = None


# ---------------------------------------------------------------------------
# Registry: (provider_key, model_name) -> pricing
# Provider keys: "vertex", "openai", "google_genai"
#
# Notes:
# - Vertex entries below use current public STANDARD pricing for <= 200K context.
# - Gemini Developer API entries below use current public STANDARD pricing
#   for <= 200K context.
# - OpenAI entries below use current public standard pricing.
# ---------------------------------------------------------------------------

_PRICING: dict[tuple[str, str], ModelPricing] = {
    # -----------------------------------------------------------------------
    # Google Vertex AI
    # -----------------------------------------------------------------------

    # Legacy placeholders: current public Google pricing pages no longer expose
    # Gemini 1.5 in the same modern per-1M-token tables used for newer models.
    # Keep existing values unless you have an authoritative contract/SKU sheet.
    ("vertex", "gemini-1.5-pro-002"): ModelPricing(
        input_price_per_million=1.25,
        output_price_per_million=5.00,
        cached_input_price_per_million=0.3125,
        other_price_per_million=5.00,
    ),
    ("vertex", "gemini-1.5-pro"): ModelPricing(
        input_price_per_million=1.25,
        output_price_per_million=5.00,
        cached_input_price_per_million=0.3125,
        other_price_per_million=5.00,
    ),
    ("vertex", "gemini-1.5-flash-002"): ModelPricing(
        input_price_per_million=0.075,
        output_price_per_million=0.30,
        cached_input_price_per_million=0.01875,
        other_price_per_million=0.30,
    ),

    # Current Vertex STANDARD <= 200K public pricing.
    ("vertex", "gemini-2.5-pro"): ModelPricing(
        input_price_per_million=1.25,
        output_price_per_million=10.00,
        cached_input_price_per_million=0.125,
        other_price_per_million=10.00,
        reasoning_price_per_million=10.00,
    ),
    ("vertex", "gemini-2.5-flash"): ModelPricing(
        input_price_per_million=0.30,
        output_price_per_million=2.50,
        cached_input_price_per_million=0.03,
        other_price_per_million=2.50,
        reasoning_price_per_million=2.50,
    ),
    ("vertex", "gemini-3.1-pro-preview"): ModelPricing(
        input_price_per_million=2.00,
        output_price_per_million=12.00,
        cached_input_price_per_million=0.20,
        other_price_per_million=12.00,
        reasoning_price_per_million=12.00,
    ),
    ("vertex", "gemini-3-flash-preview"): ModelPricing(
        input_price_per_million=0.50,
        output_price_per_million=3.00,
        cached_input_price_per_million=0.05,
        other_price_per_million=3.00,
        reasoning_price_per_million=3.00,
    ),

    # -----------------------------------------------------------------------
    # Google Gemini Developer API / AI Studio ("google_genai")
    # -----------------------------------------------------------------------

    # Legacy placeholders for 1.5 — verify against your own contract if used.
    ("google_genai", "gemini-1.5-pro"): ModelPricing(
        input_price_per_million=1.25,
        output_price_per_million=5.00,
        cached_input_price_per_million=0.3125,
        other_price_per_million=5.00,
    ),
    ("google_genai", "gemini-1.5-flash"): ModelPricing(
        input_price_per_million=0.075,
        output_price_per_million=0.30,
        cached_input_price_per_million=0.01875,
        other_price_per_million=0.30,
    ),

    # Current public STANDARD <= 200K pricing.
    ("google_genai", "gemini-2.5-pro"): ModelPricing(
        input_price_per_million=1.25,
        output_price_per_million=10.00,
        cached_input_price_per_million=0.125,
        other_price_per_million=10.00,
        reasoning_price_per_million=10.00,
    ),
    ("google_genai", "gemini-2.5-flash"): ModelPricing(
        input_price_per_million=0.30,
        output_price_per_million=2.50,
        cached_input_price_per_million=0.03,
        other_price_per_million=2.50,
        reasoning_price_per_million=2.50,
    ),
    ("google_genai", "gemini-3.1-pro-preview"): ModelPricing(
        input_price_per_million=2.00,
        output_price_per_million=12.00,
        cached_input_price_per_million=0.20,
        other_price_per_million=12.00,
        reasoning_price_per_million=12.00,
    ),
    ("google_genai", "gemini-3-flash-preview"): ModelPricing(
        input_price_per_million=0.50,
        output_price_per_million=3.00,
        cached_input_price_per_million=0.05,
        other_price_per_million=3.00,
        reasoning_price_per_million=3.00,
    ),

    # -----------------------------------------------------------------------
    # OpenAI
    # -----------------------------------------------------------------------
    ("openai", "gpt-4o"): ModelPricing(
        input_price_per_million=2.50,
        cached_input_price_per_million=1.25,
        output_price_per_million=10.00,
        other_price_per_million=10.00,
    ),
    ("openai", "gpt-4o-mini"): ModelPricing(
        input_price_per_million=0.15,
        cached_input_price_per_million=0.075,
        output_price_per_million=0.60,
        other_price_per_million=0.60,
    ),
    ("openai", "gpt-4.1"): ModelPricing(
        input_price_per_million=2.00,
        cached_input_price_per_million=0.50,
        output_price_per_million=8.00,
        other_price_per_million=8.00,
    ),
    ("openai", "o3"): ModelPricing(
        input_price_per_million=2.00,
        cached_input_price_per_million=0.50,
        output_price_per_million=8.00,
        reasoning_price_per_million=8.00,
        other_price_per_million=8.00,
    ),
}

# Alias: (provider, alias_model_name) -> canonical model name used in _PRICING keys
_MODEL_ALIASES: dict[tuple[str, str], str] = {
    # Vertex aliases
    ("vertex", "gemini-1.5-pro-latest"): "gemini-1.5-pro-002",

    # Google Gemini API aliases / old preview IDs
    ("google_genai", "gemini-3.1-pro"): "gemini-3.1-pro-preview",
    ("google_genai", "gemini-2.5-pro-preview-05-06"): "gemini-2.5-pro",
    ("google_genai", "gemini-2.5-flash-preview-05-20"): "gemini-2.5-flash",

    # OpenAI aliases
    ("openai", "gpt-4o-2024-08-06"): "gpt-4o",
}

_DEFAULT_GEMINI_BILLING = ModelBillingConfig(
    cached_tokens_included_in_input=True,
    use_total_as_billed_truth=False,
    extra_tokens_are_reasoning=False,
    fallback_bill_extra_as_output=False,
)

_DEFAULT_OPENAI_BILLING = ModelBillingConfig(
    cached_tokens_included_in_input=False,
    use_total_as_billed_truth=False,
    extra_tokens_are_reasoning=False,
    fallback_bill_extra_as_output=True,
)

# Optional overrides per (provider, model); otherwise provider defaults above.
_BILLING_CONFIG: dict[tuple[str, str], ModelBillingConfig] = {
    # Gemini: if you want inferred extra tokens billed like output, set this.
    # Uncomment if this is your desired production behavior globally.
    #
    # ("google_genai", "gemini-2.5-pro"): ModelBillingConfig(
    #     cached_tokens_included_in_input=True,
    #     use_total_as_billed_truth=False,
    #     extra_tokens_are_reasoning=False,
    #     fallback_bill_extra_as_output=True,
    # ),
    # ("google_genai", "gemini-2.5-flash"): ModelBillingConfig(
    #     cached_tokens_included_in_input=True,
    #     use_total_as_billed_truth=False,
    #     extra_tokens_are_reasoning=False,
    #     fallback_bill_extra_as_output=True,
    # ),
    # ("google_genai", "gemini-3.1-pro-preview"): ModelBillingConfig(
    #     cached_tokens_included_in_input=True,
    #     use_total_as_billed_truth=False,
    #     extra_tokens_are_reasoning=False,
    #     fallback_bill_extra_as_output=True,
    # ),
    # ("google_genai", "gemini-3-flash-preview"): ModelBillingConfig(
    #     cached_tokens_included_in_input=True,
    #     use_total_as_billed_truth=False,
    #     extra_tokens_are_reasoning=False,
    #     fallback_bill_extra_as_output=True,
    # ),
}


def _normalize_model_key(model: str) -> str:
    return model.strip()


def resolve_pricing(provider: str, model_name: str) -> ModelPricing | None:
    """Exact match, then alias match; returns None if unknown."""
    p = provider.strip().lower()
    m = _normalize_model_key(model_name)
    key = (p, m)
    if key in _PRICING:
        return _PRICING[key]
    canonical = _MODEL_ALIASES.get(key)
    if canonical is not None:
        alt = (p, canonical)
        if alt in _PRICING:
            return _PRICING[alt]
    return None


def resolve_billing_config(provider: str, model_name: str) -> ModelBillingConfig:
    """Return per-model billing strategy or provider-appropriate defaults."""
    p = provider.strip().lower()
    m = _normalize_model_key(model_name)
    key = (p, m)
    if key in _BILLING_CONFIG:
        return _BILLING_CONFIG[key]
    canonical = _MODEL_ALIASES.get(key)
    if canonical is not None:
        alt = (p, canonical)
        if alt in _BILLING_CONFIG:
            return _BILLING_CONFIG[alt]
    if p in ("vertex", "google_genai"):
        return _DEFAULT_GEMINI_BILLING
    if p == "openai":
        return _DEFAULT_OPENAI_BILLING
    return _DEFAULT_GEMINI_BILLING


def calculate_cost(provider: str, model_name: str, usage: TokenUsage) -> TokenUsage:
    """
    Backward-compatible alias for :func:`compute_billing`.

    Prefer importing ``compute_billing`` from ``billing_calculator`` for new code.
    """
    from app.services.llm.billing_calculator import compute_billing

    return compute_billing(provider, model_name, usage)