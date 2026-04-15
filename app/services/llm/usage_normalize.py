"""Map vendor-native LLM responses to :class:`TokenUsage`."""

from __future__ import annotations

from typing import Any

from app.services.llm.token_usage import TokenUsage, coalesce_total_tokens


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_dict_from_mapping(d: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable snapshot for raw_usage."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _usage_dict_from_mapping(v)
        else:
            try:
                if hasattr(v, "model_dump"):
                    out[k] = v.model_dump()
                elif hasattr(v, "__dict__"):
                    out[k] = str(v)
                else:
                    out[k] = repr(v)
            except Exception:
                out[k] = "<unserializable>"
    return out


# ---------------------------------------------------------------------------
# Gemini family (Vertex AI + Google AI Studio) — same usage_metadata shape
# ---------------------------------------------------------------------------


def _normalize_gemini_family_response(provider: str, model_name: str, response: Any) -> TokenUsage:
    raw: dict[str, Any] = {}
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        raw["prompt_token_count"] = getattr(um, "prompt_token_count", None)
        raw["candidates_token_count"] = getattr(um, "candidates_token_count", None)
        raw["total_token_count"] = getattr(um, "total_token_count", None)
        raw["cached_content_token_count"] = getattr(um, "cached_content_token_count", None)
        raw["thoughts_token_count"] = getattr(um, "thoughts_token_count", None)

    inp = _safe_int(raw.get("prompt_token_count"))
    out = _safe_int(raw.get("candidates_token_count"))
    total = _safe_int(raw.get("total_token_count"))
    cached = _safe_int(raw.get("cached_content_token_count"))
    reasoning = _safe_int(raw.get("thoughts_token_count"))

    inferred_extra: int | None = None
    if inp is not None and out is not None and total is not None:
        inferred_extra = max(0, total - inp - out)

    usage = TokenUsage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        inferred_extra_tokens=inferred_extra,
        raw_usage=_usage_dict_from_mapping(raw) if raw else None,
        provider=provider,
        model_name=model_name,
    )
    if usage.total_tokens is None:
        usage.total_tokens = coalesce_total_tokens(usage)
    return usage


def normalize_vertex_response(model_name: str, response: Any) -> TokenUsage:
    return _normalize_gemini_family_response("vertex", model_name, response)


def normalize_google_genai_response(model_name: str, response: Any) -> TokenUsage:
    return _normalize_gemini_family_response("google_genai", model_name, response)


# ---------------------------------------------------------------------------
# OpenAI (chat.completions)
# ---------------------------------------------------------------------------


def _openai_usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump()
        except Exception:
            pass
    out: dict[str, Any] = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        out[name] = getattr(usage, name, None)
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        out["prompt_tokens_details"] = (
            details.model_dump() if hasattr(details, "model_dump") else details
        )
    cdetails = getattr(usage, "completion_tokens_details", None)
    if cdetails is not None:
        out["completion_tokens_details"] = (
            cdetails.model_dump() if hasattr(cdetails, "model_dump") else cdetails
        )
    return out


def normalize_openai_response(model_name: str, response: Any) -> TokenUsage:
    u = getattr(response, "usage", None)
    raw = _openai_usage_to_dict(u)
    inp = _safe_int(raw.get("prompt_tokens"))
    out = _safe_int(raw.get("completion_tokens"))
    total = _safe_int(raw.get("total_tokens"))

    reasoning: int | None = None
    cdetails = raw.get("completion_tokens_details")
    if isinstance(cdetails, dict):
        reasoning = _safe_int(cdetails.get("reasoning_tokens"))
    elif cdetails is not None:
        reasoning = _safe_int(getattr(cdetails, "reasoning_tokens", None))

    prompt_details = raw.get("prompt_tokens_details")

    usage = TokenUsage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        reasoning_tokens=reasoning,
        cached_tokens=None,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=cdetails if isinstance(cdetails, (dict, list)) else cdetails,
        raw_usage=_usage_dict_from_mapping(raw) if raw else None,
        provider="openai",
        model_name=model_name,
    )
    if usage.total_tokens is None:
        usage.total_tokens = coalesce_total_tokens(usage)
    return usage


def normalize_usage(provider: str, model_name: str, raw_response: Any) -> TokenUsage:
    """
    Dispatch normalization by logical provider key.

    *provider* must match pricing keys: ``vertex``, ``openai``, ``google_genai``.
    """
    p = provider.strip().lower()
    if p == "vertex":
        return normalize_vertex_response(model_name, raw_response)
    if p == "openai":
        return normalize_openai_response(model_name, raw_response)
    if p == "google_genai":
        return normalize_google_genai_response(model_name, raw_response)
    raise ValueError(f"Unknown provider for usage normalization: {provider!r}")
