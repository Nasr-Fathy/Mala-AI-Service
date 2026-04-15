"""Provider-aware billing: billable buckets, inferred extra tokens, USD costs."""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.llm.billing_types import BillingBreakdown, ModelBillingConfig
from app.services.llm.pricing_registry import (
    ModelPricing,
    resolve_billing_config,
    resolve_pricing,
)
from app.services.llm.token_usage import TokenUsage

logger = get_logger(__name__)


def compute_billing(provider: str, model_name: str, usage: TokenUsage) -> TokenUsage:
    """
    Attach :class:`BillingBreakdown` and legacy ``cost_*`` rollups on *usage*.

    Unknown pricing → no billing object, costs remain None (warning logged).
    """
    pricing = resolve_pricing(provider, model_name)
    if pricing is None:
        logger.warning(
            "llm_pricing_unknown",
            provider=provider,
            model_name=model_name,
            hint="Add an entry to pricing_registry._PRICING or _MODEL_ALIASES",
        )
        return usage.with_costs(cost_input=None, cost_output=None, cost_total=None)

    config = resolve_billing_config(provider, model_name)
    p = provider.strip().lower()

    if p in ("vertex", "google_genai"):
        return _compute_gemini_billing(provider, model_name, usage, pricing, config)
    if p == "openai":
        return _compute_openai_billing(provider, model_name, usage, pricing, config)

    logger.warning("llm_billing_unknown_provider", provider=provider, model_name=model_name)
    return _compute_openai_billing(provider, model_name, usage, pricing, config)


def _per_million(tokens: float, price_per_million: float) -> float:
    return (tokens / 1_000_000.0) * price_per_million


def _compute_gemini_billing(
    provider: str,
    model_name: str,
    usage: TokenUsage,
    pricing: ModelPricing,
    config: ModelBillingConfig,
) -> TokenUsage:
    P = usage.input_tokens
    C = usage.output_tokens
    T = usage.total_tokens
    cache = usage.cached_tokens
    thoughts = usage.reasoning_tokens

    notes: list[str] = []
    inferred: int | None = None
    if P is not None and C is not None and T is not None:
        inferred = max(0, T - P - C)

    billable_cached = 0
    billable_uncached = 0
    p_tokens = int(P or 0)
    if config.cached_tokens_included_in_input:
        billable_cached = max(0, int(cache or 0))
        billable_uncached = max(0, p_tokens - billable_cached)
        if billable_cached > p_tokens and P is not None:
            notes.append("cached_tokens_exceed_input_tokens")
            logger.warning(
                "llm_cached_tokens_exceed_input",
                provider=provider,
                model_name=model_name,
                input_tokens=P,
                cached_tokens=billable_cached,
            )
    else:
        billable_uncached = p_tokens
        billable_cached = 0

    billable_out = int(C or 0)
    br = 0
    bo = 0

    # Gemini rule: keep completion output bucket explicit; inferred extra stays in
    # a separate "other" bucket unless reasoning mode is explicitly configured.
    if thoughts is not None and thoughts > 0 and config.extra_tokens_are_reasoning:
        br = int(thoughts)
    elif inferred is not None and inferred > 0:
        bo = inferred

    # --- USD: prompt ---
    cost_uncached: float | None = None
    if billable_uncached > 0:
        cost_uncached = _per_million(float(billable_uncached), pricing.input_price_per_million)

    cost_cached: float | None = None
    if billable_cached > 0:
        rate = pricing.cached_input_price_per_million
        if rate is None:
            rate = pricing.input_price_per_million
            notes.append("cached_input_used_input_price_assumption")
            logger.warning(
                "llm_cached_price_fallback",
                provider=provider,
                model_name=model_name,
                assumption="cached_input_price_per_million unset; using input_price_per_million",
            )
        cost_cached = _per_million(float(billable_cached), rate)

    # --- USD: completion / reasoning / other ---
    reasoning_rate = pricing.reasoning_price_per_million or pricing.output_price_per_million
    if pricing.reasoning_price_per_million is None and br > 0:
        notes.append("reasoning_used_output_price_assumption")

    cost_out = _per_million(float(billable_out), pricing.output_price_per_million) if billable_out > 0 else None
    cost_reas = _per_million(float(br), reasoning_rate) if br > 0 else None

    cost_oth: float | None = None
    if bo > 0:
        rate_other = pricing.other_price_per_million
        if rate_other is None:
            if config.fallback_bill_extra_as_output:
                rate_other = pricing.output_price_per_million
                notes.append("other_tokens_billed_at_output_price_fallback")
                logger.warning(
                    "llm_other_price_fallback_to_output",
                    provider=provider,
                    model_name=model_name,
                    billable_other_tokens=bo,
                    assumption="other_price_per_million unset; using output_price_per_million",
                )
            else:
                logger.warning(
                    "llm_other_price_missing",
                    provider=provider,
                    model_name=model_name,
                    billable_other_tokens=bo,
                    hint="Set other_price_per_million or enable fallback_bill_extra_as_output",
                )
                notes.append("other_tokens_unpriced")
        if rate_other is not None:
            cost_oth = _per_million(float(bo), rate_other)

    parts = [x for x in (cost_uncached, cost_cached, cost_out, cost_reas, cost_oth) if x is not None]
    cost_total = float(sum(parts)) if parts else None

    attributed = billable_uncached + billable_cached + billable_out + br + bo
    recon: str | None = None
    if T is not None and attributed != T:
        gap_note = f"total_token_count={T} != sum(billable_buckets)={attributed}"
        notes.append(gap_note)
        if config.use_total_as_billed_truth:
            recon = gap_note
            logger.warning(
                "llm_billing_total_reconciliation",
                provider=provider,
                model_name=model_name,
                warning=recon,
            )

    bd = BillingBreakdown(
        inferred_extra_tokens=inferred,
        billable_input_tokens=billable_uncached,
        billable_cached_input_tokens=billable_cached,
        billable_output_tokens=billable_out,
        billable_reasoning_tokens=br,
        billable_other_tokens=bo,
        cost_input=cost_uncached,
        cost_cached_input=cost_cached,
        cost_output=cost_out,
        cost_reasoning=cost_reas,
        cost_other=cost_oth,
        cost_total=cost_total,
        reconciliation_warning=recon,
        billing_notes=notes,
    )
    return usage.with_billing(bd)


def _compute_openai_billing(
    provider: str,
    model_name: str,
    usage: TokenUsage,
    pricing: ModelPricing,
    config: ModelBillingConfig,
) -> TokenUsage:
    P = usage.input_tokens
    C = usage.output_tokens
    T = usage.total_tokens
    reasoning = usage.reasoning_tokens or 0

    inferred: int | None = None
    if P is not None and C is not None and T is not None:
        inferred = max(0, T - P - C)

    c = int(C or 0)
    r = int(reasoning)
    non_reasoning = max(0, c - r)
    br = r
    bout = non_reasoning
    bo = 0

    if inferred is not None and inferred > 0:
        if config.extra_tokens_are_reasoning:
            br += inferred
        elif config.fallback_bill_extra_as_output:
            bout += inferred
        else:
            bo = inferred

    billable_cached = 0
    billable_uncached = int(P or 0)

    cost_in = _per_million(float(billable_uncached), pricing.input_price_per_million) if billable_uncached > 0 else None

    reasoning_rate = pricing.reasoning_price_per_million or pricing.output_price_per_million
    cost_out = _per_million(float(bout), pricing.output_price_per_million) if bout > 0 else None
    cost_reas = _per_million(float(br), reasoning_rate) if br > 0 else None

    cost_oth: float | None = None
    if bo > 0:
        rate_other = pricing.other_price_per_million
        if rate_other is None:
            logger.warning(
                "llm_other_price_missing",
                provider=provider,
                model_name=model_name,
                billable_other_tokens=bo,
            )
        else:
            cost_oth = _per_million(float(bo), rate_other)

    parts = [x for x in (cost_in, cost_out, cost_reas, cost_oth) if x is not None]
    cost_total = float(sum(parts)) if parts else None

    notes: list[str] = []
    recon: str | None = None
    attributed = billable_uncached + billable_cached + bout + br + bo
    if T is not None and attributed != T:
        gap_note = f"total_token_count={T} != sum(billable_buckets)={attributed}"
        notes.append(gap_note)
        if config.use_total_as_billed_truth:
            recon = gap_note
            logger.warning(
                "llm_billing_total_reconciliation",
                provider=provider,
                model_name=model_name,
                warning=recon,
            )

    bd = BillingBreakdown(
        inferred_extra_tokens=inferred,
        billable_input_tokens=billable_uncached,
        billable_cached_input_tokens=billable_cached,
        billable_output_tokens=bout,
        billable_reasoning_tokens=br,
        billable_other_tokens=bo,
        cost_input=cost_in,
        cost_cached_input=None,
        cost_output=cost_out,
        cost_reasoning=cost_reas,
        cost_other=cost_oth,
        cost_total=cost_total,
        reconciliation_warning=recon,
        billing_notes=notes,
    )
    return usage.with_billing(bd)
