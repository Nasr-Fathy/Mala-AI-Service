"""Build :class:`LLMResponse`, structured logs, LangSmith metadata, and costs."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.llm.base import LLMResponse
from dataclasses import replace

from app.core.config import get_settings
from app.services.llm.billing_calculator import compute_billing
from app.services.llm.token_usage import TokenUsage, coalesce_total_tokens

logger = get_logger(__name__)


def supplement_missing_token_estimates(
    usage: TokenUsage,
    *,
    content_parts: list[Any] | None = None,
    raw_text: str = "",
) -> TokenUsage:
    """
    When the vendor omits usage metadata, fall back to the legacy char/4 heuristic
    so stats and estimates stay non-zero where they used to.

    For Gemini, if the API returned partial usage (prompt and/or candidate counts)
    but omitted ``total_token_count``, we do **not** set ``total_tokens`` to
    ``input + output`` — that would hide billable reasoning/extra tokens. A
    synthetic total is only applied when *both* input and output were missing from
    the response and filled entirely from heuristics.
    """
    p = (usage.provider or "").strip().lower()
    is_gemini = p in ("vertex", "google_genai")
    api_had_partial = usage.input_tokens is not None or usage.output_tokens is not None

    final_in = usage.input_tokens
    if final_in is None and content_parts is not None:
        final_in = sum(len(str(p)) for p in content_parts) // 4
    final_out = usage.output_tokens
    if final_out is None:
        final_out = max(0, len(raw_text) // 4)
    final_total = usage.total_tokens
    if final_total is None:
        tmp = replace(usage, input_tokens=final_in, output_tokens=final_out, total_tokens=None)
        if is_gemini and api_had_partial:
            final_total = None
            logger.warning(
                "llm_gemini_total_token_count_missing",
                provider=usage.provider,
                model_name=usage.model_name,
                input_tokens=final_in,
                output_tokens=final_out,
                hint="total_token_count omitted; gap attribution requires API total",
            )
        elif is_gemini and not api_had_partial:
            if final_in is not None and final_out is not None:
                final_total = final_in + final_out
            else:
                final_total = None
        else:
            final_total = coalesce_total_tokens(tmp)
    return replace(
        usage,
        input_tokens=final_in,
        output_tokens=final_out,
        total_tokens=final_total,
    )


def build_langsmith_usage_metadata(usage: TokenUsage) -> dict[str, Any]:
    """
    Metadata keys compatible with LangSmith LLM runs (flat + nested usage_metadata).

    ``usage_metadata`` includes raw token counts plus billable buckets and
    granular USD when :attr:`TokenUsage.billing` is present. Full detail remains in
    ``billing_breakdown``; ``raw_usage`` is preserved for vendor-native fields.
    """
    um: dict[str, Any] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }
    if usage.reasoning_tokens is not None:
        um["reasoning_tokens"] = usage.reasoning_tokens
    if usage.cached_tokens is not None:
        um["cached_tokens"] = usage.cached_tokens
    if usage.inferred_extra_tokens is not None:
        um["inferred_extra_tokens"] = usage.inferred_extra_tokens

    bd = usage.billing
    if bd is not None:
        um["billable_input_tokens"] = bd.billable_input_tokens
        um["billable_cached_input_tokens"] = bd.billable_cached_input_tokens
        um["billable_output_tokens"] = bd.billable_output_tokens
        um["billable_reasoning_tokens"] = bd.billable_reasoning_tokens
        um["billable_other_tokens"] = bd.billable_other_tokens
        um["cost_input_usd"] = bd.cost_input
        um["cost_cached_input_usd"] = bd.cost_cached_input
        um["cost_output_usd"] = bd.cost_output
        um["cost_reasoning_usd"] = bd.cost_reasoning
        um["cost_other_usd"] = bd.cost_other
        um["cost_total_usd"] = bd.cost_total

    meta: dict[str, Any] = {
        "ls_provider": usage.provider,
        "ls_model_name": usage.model_name,
        "usage_metadata": um,
    }
    if usage.raw_usage is not None:
        meta["raw_usage"] = usage.raw_usage
    if bd is not None:
        meta["billing_breakdown"] = bd.to_log_dict()
    if usage.cost_input is not None:
        meta["cost_input_usd"] = usage.cost_input
    if usage.cost_output is not None:
        meta["cost_output_usd"] = usage.cost_output
    if usage.cost_total is not None:
        meta["cost_total_usd"] = usage.cost_total
    return meta


def attach_langsmith_llm_usage(usage: TokenUsage) -> None:
    """Merge usage/cost into the current LangSmith run, if any."""
    try:
        from langsmith.run_helpers import set_run_metadata
    except ImportError:
        return
    try:
        set_run_metadata(**build_langsmith_usage_metadata(usage))
    except Exception:
        logger.debug("langsmith_metadata_attach_failed", exc_info=True)


def log_llm_usage_after_response(
    label: str,
    usage: TokenUsage,
    *,
    log_raw_usage_debug: bool = False,
) -> None:
    bd = usage.billing
    payload: dict[str, Any] = {
        "label": label,
        "provider": usage.provider,
        "model_name": usage.model_name,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_tokens": usage.cached_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "inferred_extra_tokens": usage.inferred_extra_tokens,
        "cost_input": usage.cost_input,
        "cost_output": usage.cost_output,
        "cost_total": usage.cost_total,
    }
    if bd is not None:
        payload.update(
            {
                "billable_input_tokens": bd.billable_input_tokens,
                "billable_cached_input_tokens": bd.billable_cached_input_tokens,
                "billable_output_tokens": bd.billable_output_tokens,
                "billable_reasoning_tokens": bd.billable_reasoning_tokens,
                "billable_other_tokens": bd.billable_other_tokens,
                "cost_input": bd.cost_input,
                "cost_cached_input": bd.cost_cached_input,
                "cost_output": bd.cost_output,
                "cost_reasoning": bd.cost_reasoning,
                "cost_other": bd.cost_other,
                "cost_total": bd.cost_total,
                "cost_uncached_input_usd": bd.cost_input,
                "cost_cached_input_usd": bd.cost_cached_input,
                "cost_output_usd": bd.cost_output,
                "cost_reasoning_usd": bd.cost_reasoning,
                "cost_other_usd": bd.cost_other,
                "cost_total_usd": bd.cost_total,
                "reconciliation_warning": bd.reconciliation_warning,
                "billing_notes": bd.billing_notes,
            }
        )
    logger.info("llm_usage", **payload)
    if log_raw_usage_debug and usage.raw_usage is not None:
        logger.debug("llm_raw_usage", label=label, raw_usage=usage.raw_usage)


def finalize_llm_response(
    *,
    provider: str,
    model_name: str,
    raw_vendor_response: Any,
    content: dict[str, Any],
    raw_text: str,
    attempt: int,
    elapsed_ms: int,
    label: str,
    extra_metadata: dict[str, Any] | None = None,
    log_raw_usage_debug: bool = False,
    content_parts: list[Any] | None = None,
) -> LLMResponse:
    """
    Normalize usage, compute cost, log, attach LangSmith, and build :class:`LLMResponse`.
    """
    from app.services.llm.usage_normalize import normalize_usage

    usage = normalize_usage(provider, model_name, raw_vendor_response)
    usage = supplement_missing_token_estimates(usage, content_parts=content_parts, raw_text=raw_text)
    usage = compute_billing(provider, model_name, usage)
    debug_raw = log_raw_usage_debug or get_settings().DEBUG
    log_llm_usage_after_response(label, usage, log_raw_usage_debug=debug_raw)
    attach_langsmith_llm_usage(usage)

    est_in = usage.input_tokens if usage.input_tokens is not None else 0
    est_out = usage.output_tokens if usage.output_tokens is not None else 0
    meta = dict(extra_metadata) if extra_metadata else {}
    return LLMResponse(
        content=content,
        raw_text=raw_text,
        model=model_name,
        estimated_input_tokens=est_in,
        estimated_output_tokens=est_out,
        attempt=attempt,
        elapsed_ms=elapsed_ms,
        usage=usage,
        metadata=meta,
    )
