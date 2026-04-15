"""Billing breakdown and per-model billing strategy types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelBillingConfig:
    """
    How to interpret usage fields for a given provider/model.

    Gemini defaults: cached prompt is a subset of prompt_token_count; gap T-P-C
    may need attribution via reasoning vs other vs output fallback.

    **use_total_as_billed_truth**: When ``total_tokens`` from the API does not
    equal the sum of billable buckets (prompt + cached + output + reasoning +
    other), we always record that mismatch in ``billing_notes``. If this flag
    is ``True``, we also set ``reconciliation_warning`` and emit a structured
    ``WARNING`` log (``llm_billing_total_reconciliation``). The flag does **not**
    rescale token buckets or costs to force equality with ``total_tokens``; use
    it for strict audit trails, not automatic cost correction.
    """

    cached_tokens_included_in_input: bool = True
    use_total_as_billed_truth: bool = False
    extra_tokens_are_reasoning: bool = False
    fallback_bill_extra_as_output: bool = False


@dataclass
class BillingBreakdown:
    """Auditable billable token buckets and USD costs (single response)."""

    inferred_extra_tokens: int | None = None
    billable_input_tokens: int | None = None
    billable_cached_input_tokens: int | None = None
    billable_output_tokens: int | None = None
    billable_reasoning_tokens: int | None = None
    billable_other_tokens: int | None = None
    # USD (granular)
    cost_input: float | None = None  # uncached prompt
    cost_cached_input: float | None = None
    cost_output: float | None = None  # candidate / completion text (non-reasoning portion when split)
    cost_reasoning: float | None = None
    cost_other: float | None = None
    cost_total: float | None = None
    reconciliation_warning: str | None = None
    billing_notes: list[str] = field(default_factory=list)

    def to_log_dict(self) -> dict[str, float | int | str | list[str] | None]:
        return {
            "inferred_extra_tokens": self.inferred_extra_tokens,
            "billable_input_tokens": self.billable_input_tokens,
            "billable_cached_input_tokens": self.billable_cached_input_tokens,
            "billable_output_tokens": self.billable_output_tokens,
            "billable_reasoning_tokens": self.billable_reasoning_tokens,
            "billable_other_tokens": self.billable_other_tokens,
            "cost_input": self.cost_input,
            "cost_cached_input": self.cost_cached_input,
            "cost_output": self.cost_output,
            "cost_reasoning": self.cost_reasoning,
            "cost_other": self.cost_other,
            "cost_total": self.cost_total,
            "reconciliation_warning": self.reconciliation_warning,
            "billing_notes": list(self.billing_notes),
        }
