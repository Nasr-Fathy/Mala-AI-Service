"""Provider-agnostic token usage and cost representation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.services.llm.billing_types import BillingBreakdown


@dataclass
class TokenUsage:
    """Normalized LLM usage for any provider."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    inferred_extra_tokens: int | None = None
    prompt_tokens_details: Any | None = None
    completion_tokens_details: Any | None = None
    raw_usage: dict[str, Any] | None = None
    cost_input: float | None = None
    cost_output: float | None = None
    cost_total: float | None = None
    provider: str = ""
    model_name: str = ""
    billing: BillingBreakdown | None = None

    def with_costs(
        self,
        *,
        cost_input: float | None,
        cost_output: float | None,
        cost_total: float | None,
    ) -> TokenUsage:
        return replace(
            self,
            cost_input=cost_input,
            cost_output=cost_output,
            cost_total=cost_total,
        )

    def with_billing(self, breakdown: BillingBreakdown) -> TokenUsage:
        """Attach billing breakdown and legacy rollup cost fields."""
        if not isinstance(breakdown, BillingBreakdown):
            raise TypeError("breakdown must be BillingBreakdown")

        prompt_side = _sum_optional_usd(breakdown.cost_input, breakdown.cost_cached_input)
        completion_side = _sum_optional_usd(
            breakdown.cost_output,
            breakdown.cost_reasoning,
            breakdown.cost_other,
        )
        return replace(
            self,
            inferred_extra_tokens=breakdown.inferred_extra_tokens,
            billing=breakdown,
            cost_input=prompt_side,
            cost_output=completion_side,
            cost_total=breakdown.cost_total,
        )


def _sum_optional_usd(*parts: float | None) -> float | None:
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return float(sum(present))


def coalesce_total_tokens(usage: TokenUsage) -> int | None:
    """
    Prefer API-reported total.

    For Gemini (``vertex`` / ``google_genai``), never infer total as input+output:
    ``total_token_count`` may include reasoning/cache components not reflected in
    prompt + candidates alone. When the API omits total, return ``None`` so
    callers do not erase the billed gap; :func:`supplement_missing_token_estimates`
    may still synthesize input+output for fully-estimated usage.
    """
    if usage.total_tokens is not None:
        return usage.total_tokens
    p = (usage.provider or "").strip().lower()
    if p in ("vertex", "google_genai"):
        return None
    if usage.input_tokens is not None and usage.output_tokens is not None:
        return usage.input_tokens + usage.output_tokens
    return None
