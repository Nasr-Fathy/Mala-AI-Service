"""Centralised JSON sanitisation pipeline for LLM responses.

Every LLM response passes through :func:`parse_llm_json` before downstream
usage.  The function tries multiple cleanup strategies in order and raises a
diagnostic exception when all attempts fail so the caller's retry mechanism
can re-attempt the LLM call.
"""
from __future__ import annotations

import json
import re
from typing import Any

import json_repair

from app.core.exceptions import LLMResponseParseError
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_STRINGIFY_DEPTH = 3
_PREVIEW_LEN = 500

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON|javascript|js|Python|python)?\s*\n?"
    r"(.*?)"
    r"\n?\s*```\s*$",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class LLMJsonParseError(LLMResponseParseError):
    """Raised when *all* JSON sanitisation stages fail.

    Carries diagnostic metadata so that the final
    :class:`LLMRetryExhaustedError` can expose useful context.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        raw_preview: str,
        stages_tried: list[dict[str, str]],
    ) -> None:
        self.stage = stage
        self.raw_preview = raw_preview
        self.stages_tried = stages_tried
        details: dict[str, Any] = {
            "failed_stage": stage,
            "raw_preview": raw_preview[:_PREVIEW_LEN],
            "stages_tried": stages_tried,
        }
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preview(raw: str) -> str:
    return raw[:_PREVIEW_LEN]


def _is_structured(obj: Any) -> bool:
    """Return *True* only for dict or list (structured JSON)."""
    return isinstance(obj, (dict, list))


def _unwrap_stringified(text: str, max_depth: int = _MAX_STRINGIFY_DEPTH) -> str:
    """Recursively unwrap stringified JSON (``"\"{ … }\""``).

    Stops when :func:`json.loads` no longer returns a string, when the
    unwrapped string does not look like JSON, or when *max_depth* is reached.
    """
    current = text
    for _ in range(max_depth):
        try:
            inner = json.loads(current)
        except (json.JSONDecodeError, TypeError):
            break
        if not isinstance(inner, str):
            break
        # The inner string might be a JSON-encoded string itself (e.g. '"val"')
        # or it might be actual JSON content. Only keep unwrapping if it looks
        # like it contains a JSON object or array after stripping quotes.
        candidate = inner.strip()
        if candidate.startswith(("{", "[")):
            current = candidate
        elif candidate.startswith('"') and candidate.endswith('"'):
            # Still a quoted string — continue unwrapping
            current = inner
        else:
            break
    return current


def _strip_fences(text: str) -> str:
    """Remove markdown code fences (`` ```json … ``` `` etc.)."""
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    # Fallback: manual strip for edge-case fence variants
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        else:
            stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def _extract_json_balanced(text: str) -> str | None:
    """Extract the first valid JSON object or array using balanced-delimiter scan.

    Walks the string once (O(n)), respecting string boundaries and escape
    sequences.  Returns the first substring that forms a complete, valid
    top-level JSON object ``{…}`` or array ``[…]``.
    """
    # Try to find top-level balanced objects and arrays.
    # Object scan first (most common case).
    obj = _find_balanced(text, "{", "}")
    if obj is not None:
        return obj
    return _find_balanced(text, "[", "]")


def _find_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    idx = 0

    while idx < len(text):
        ch = text[idx]
        if escape:
            escape = False
            idx += 1
            continue
        if ch == "\\" and in_string:
            escape = True
            idx += 1
            continue
        if ch == '"':
            in_string = not in_string
            idx += 1
            continue
        if in_string:
            idx += 1
            continue
        if ch == open_ch:
            if depth == 0:
                start = idx
            depth += 1
        elif ch == close_ch:
            if depth > 0:
                depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : idx + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    # This balanced region wasn't valid JSON.
                    # Restart scan from after the failed start.
                    idx = start + 1
                    start = None
                    depth = 0
                    in_string = False
                    escape = False
                    continue
        idx += 1

    # If we exhausted the string with an unbalanced opener still active,
    # restart from after the original start to find later candidates.
    if start is not None and depth > 0:
        return _find_balanced(text[start + 1 :], open_ch, close_ch)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Sanitise and parse an LLM response into a dict.

    Pipeline stages (tried in order):
      1. Direct ``json.loads`` on trimmed input
      2. Strip markdown code fences, then parse
      3. Unwrap stringified JSON (up to 3 levels), then parse
      4. Balanced-brace/bracket extraction from mixed text
      5. ``json_repair`` as a last resort

    Returns a ``dict``.  Single-element lists ``[{…}]`` are unwrapped to the
    contained dict.  Bare lists with >1 element or non-dict elements raise
    :class:`LLMJsonParseError` because downstream code expects a dict.

    Raises :class:`LLMJsonParseError` on total failure.
    """
    text = raw.strip()

    if not text:
        raise LLMJsonParseError(
            "LLM returned empty response",
            stage="pre_check",
            raw_preview="",
            stages_tried=[{"stage": "pre_check", "error": "empty input"}],
        )

    stages_tried: list[dict[str, str]] = []

    def _record(stage: str, error: str) -> None:
        stages_tried.append({"stage": stage, "error": error})

    # ----- Stage 1: direct parse -------------------------------------------
    try:
        result = json.loads(text)
        if _is_structured(result):
            return _normalise_to_dict(result)
        _record("direct_parse", f"Result is {type(result).__name__}, expected dict/list")
    except json.JSONDecodeError as e:
        _record("direct_parse", str(e))

    # ----- Stage 2: strip fences -------------------------------------------
    try:
        stripped = _strip_fences(text)
        if stripped != text:
            result = json.loads(stripped)
            if _is_structured(result):
                logger.debug("parse_llm_json_stage", stage="strip_fences", success=True)
                return _normalise_to_dict(result)
            _record("strip_fences", f"Result is {type(result).__name__}, expected dict/list")
        else:
            _record("strip_fences", "no fences detected")
    except json.JSONDecodeError as e:
        _record("strip_fences", str(e))

    # ----- Stage 3: unwrap stringified JSON --------------------------------
    try:
        unwrapped = _unwrap_stringified(text)
        if unwrapped != text:
            result = json.loads(unwrapped)
            if _is_structured(result):
                logger.debug("parse_llm_json_stage", stage="unwrap_stringified", success=True)
                return _normalise_to_dict(result)
            _record("unwrap_stringified", f"Result is {type(result).__name__}, expected dict/list")
        else:
            _record("unwrap_stringified", "no string wrapping detected")
    except json.JSONDecodeError as e:
        _record("unwrap_stringified", str(e))

    # ----- Stage 4: balanced extraction ------------------------------------
    extracted = _extract_json_balanced(text)
    if extracted is not None:
        try:
            result = json.loads(extracted)
            if _is_structured(result):
                logger.debug(
                    "parse_llm_json_stage",
                    stage="balanced_extraction",
                    success=True,
                    extracted_len=len(extracted),
                )
                return _normalise_to_dict(result)
            _record("balanced_extraction", f"Result is {type(result).__name__}, expected dict/list")
        except json.JSONDecodeError as e:
            _record("balanced_extraction", str(e))
    else:
        _record("balanced_extraction", "no balanced JSON found")

    # ----- Stage 5: json_repair -------------------------------------------
    try:
        repaired = json_repair.loads(text)
        if _is_structured(repaired):
            logger.warning(
                "parse_llm_json_repair_applied",
                raw_preview=_preview(text),
                repaired_preview=_preview(json.dumps(repaired, ensure_ascii=False)),
            )
            return _normalise_to_dict(repaired)
        _record("json_repair", f"Result is {type(repaired).__name__}, expected dict/list")
    except Exception as e:
        _record("json_repair", str(e))

    # ----- Total failure ---------------------------------------------------
    last_stage = stages_tried[-1]["stage"] if stages_tried else "unknown"
    raise LLMJsonParseError(
        f"Failed to parse LLM response as JSON after {len(stages_tried)} attempts",
        stage=last_stage,
        raw_preview=_preview(text),
        stages_tried=stages_tried,
    )


def _normalise_to_dict(result: dict[str, Any] | list[Any]) -> dict[str, Any]:
    """Ensure the parsed value is a dict.

    Single-element list containing a dict ``[{…}]`` is unwrapped.
    Everything else that is a list raises because downstream code expects a dict.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        if len(result) == 1 and isinstance(result[0], dict):
            logger.debug("parse_llm_json_unwrap_list", original_len=1)
            return result[0]
        raise LLMJsonParseError(
            f"LLM returned a JSON array ({len(result)} elements) but a dict was expected",
            stage="normalise",
            raw_preview=json.dumps(result, ensure_ascii=False)[:_PREVIEW_LEN],
            stages_tried=[{"stage": "normalise", "error": "array returned, dict expected"}],
        )
    # Should never reach here because of _is_structured guards
    raise LLMJsonParseError(
        f"LLM returned {type(result).__name__} but a dict was expected",
        stage="normalise",
        raw_preview=str(result)[:_PREVIEW_LEN],
        stages_tried=[{"stage": "normalise", "error": f"{type(result).__name__} returned"}],
    )
