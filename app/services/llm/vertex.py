from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from langsmith import traceable

from app.core.config import Settings
from app.core.exceptions import (
    LLMError,
    LLMResponseParseError,
    LLMRetryExhaustedError,
)
from app.services.llm.json_parser import parse_llm_json
from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs
from app.services.capture.capture_service import CaptureService
from app.services.llm.base import BaseLLMClient, GenerationConfig, LLMResponse
from app.services.llm.llm_finalize import finalize_llm_response

logger = get_logger(__name__)

# HTTP status codes for retryable / client errors from the google-genai SDK.
_RETRYABLE_CODES = {429, 503, 504}
_INVALID_ARGUMENT_CODE = 400


class VertexLLMClient(BaseLLMClient):
    """Async Vertex AI (Gemini) client using the google-genai SDK with exponential-backoff retry."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: genai.Client | None = None

        # stats
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_tokens = 0

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _get_client(self) -> genai.Client:
        """Lazy-initialize the google-genai Client for Vertex AI."""
        if self._client is None:
            self._client = genai.Client(
                vertexai=self._settings.VERTEX_USE_VERTEXAI,
                project=self._settings.GOOGLE_CLOUD_PROJECT_ID,
                location=self._settings.VERTEX_LOCATION,
            )
            logger.info(
                "vertex_ai_initialized",
                project=self._settings.GOOGLE_CLOUD_PROJECT_ID,
                location=self._settings.VERTEX_LOCATION,
                model=self._settings.VERTEX_MODEL,
            )
        return self._client

    # ------------------------------------------------------------------
    # Model-family helpers
    # ------------------------------------------------------------------

    def _is_gemini3_family(self) -> bool:
        """Return True when the configured model belongs to the Gemini 3+ family.

        Gemini 3+ models support *thinking_level* but reject *thinking_budget*.
        Older models (Gemini 2.5 and below) support *thinking_budget* but reject
        *thinking_level*.
        """
        model = (self._settings.VERTEX_MODEL or "").lower()
        return bool(re.match(r"gemini-3", model))

    # ------------------------------------------------------------------
    # Config mapping
    # ------------------------------------------------------------------

    def _build_thinking_config(self, cfg: GenerationConfig) -> types.ThinkingConfig | None:
        """Build a ThinkingConfig respecting the model-family constraint.

        Rules enforced per Google documentation:
        - Gemini 3+: only *thinking_level* is accepted; *thinking_budget* causes an error.
        - Gemini 2.5 / older: only *thinking_budget* is accepted; *thinking_level* causes an error.
        - Never send both in the same request.
        """
        is_gemini3 = self._is_gemini3_family()
        budget = cfg.thinking_budget
        level = cfg.thinking_level

        if is_gemini3:
            if level is not None:
                return types.ThinkingConfig(thinking_level=level)
            # If the caller set thinking_budget on a Gemini 3 model, log a warning
            # and skip it rather than sending an invalid request.
            if budget is not None:
                logger.warning(
                    "thinking_budget_ignored_for_gemini3",
                    model=self._settings.VERTEX_MODEL,
                    hint="Gemini 3+ models require thinking_level, not thinking_budget",
                )
            return None
        else:
            if budget is not None:
                return types.ThinkingConfig(thinking_budget=budget)
            if level is not None:
                logger.warning(
                    "thinking_level_ignored_for_legacy_model",
                    model=self._settings.VERTEX_MODEL,
                    hint="Gemini 2.5 / older models require thinking_budget, not thinking_level",
                )
            return None

    def _to_genai_config(self, cfg: GenerationConfig) -> types.GenerateContentConfig:
        """Convert our internal GenerationConfig to a google-genai GenerateContentConfig."""
        kw: dict[str, Any] = {
            "max_output_tokens": cfg.max_output_tokens,
            "temperature": cfg.temperature,
        }

        if cfg.response_json:
            kw["response_mime_type"] = "application/json"

        thinking = self._build_thinking_config(cfg)
        if thinking is not None:
            kw["thinking_config"] = thinking

        return types.GenerateContentConfig(**kw)

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        s = self._settings
        base = min(s.LLM_BASE_DELAY * (2 ** attempt), s.LLM_MAX_DELAY)
        jitter = random.uniform(0, base * s.LLM_JITTER_FACTOR)
        return base + jitter

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Return True for transient API errors worth retrying."""
        if isinstance(exc, genai_errors.APIError):
            return exc.code in _RETRYABLE_CODES
        return False

    @staticmethod
    def _is_invalid_argument_error(exc: Exception) -> bool:
        """Return True for 400 Bad Request errors."""
        if isinstance(exc, genai_errors.APIError):
            return exc.code == _INVALID_ARGUMENT_CODE
        return False

    # ------------------------------------------------------------------
    # Core generation loop
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        contents: list[Any],
        config: GenerationConfig,
        label: str,
        model_name: str | None = None,
    ) -> LLMResponse:
        self.total_calls += 1
        client = self._get_client()
        genai_config = self._to_genai_config(config)
        model = model_name or self._settings.VERTEX_MODEL
        max_retries = self._settings.LLM_MAX_RETRIES
        last_exc: BaseException | None = None
        start = time.time()

        for attempt in range(max_retries):
            try:
                logger.info("llm_attempt", label=label, attempt=attempt + 1, max_retries=max_retries)

                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=genai_config,
                )

                if not response.candidates:
                    raise LLMError("No response candidates from Gemini")

                raw_text = response.candidates[0].content.parts[0].text
                CaptureService._dump_raw_output("pass_10_metadata", raw_text)
                logger.info("llm_response", raw_text=raw_text)

                parsed = parse_llm_json(raw_text)

                self.successful_calls += 1
                elapsed = int((time.time() - start) * 1000)

                out = finalize_llm_response(
                    provider="vertex",
                    model_name=model,
                    raw_vendor_response=response,
                    content=parsed,
                    raw_text=raw_text,
                    attempt=attempt + 1,
                    elapsed_ms=elapsed,
                    label=label,
                    content_parts=contents,
                )
                ut = out.usage
                if ut is not None:
                    if ut.total_tokens is not None:
                        self.total_tokens += ut.total_tokens
                    else:
                        self.total_tokens += (ut.input_tokens or 0) + (ut.output_tokens or 0)

                logger.info("llm_success", label=label, elapsed_ms=elapsed)

                return out

            except genai_errors.APIError as e:
                if self._is_retryable_error(e):
                    last_exc = e
                    delay = self._delay(attempt)
                    logger.error(
                        "llm_retryable_error",
                        label=label,
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        error=str(e),
                        error_code=e.code,
                        delay_s=round(delay, 1),
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
                elif self._is_invalid_argument_error(e):
                    self.failed_calls += 1
                    logger.error(
                        "llm_invalid_argument",
                        label=label,
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        error=str(e),
                        error_code=e.code,
                        exc_info=True,
                    )
                    raise LLMError(f"Invalid LLM request: {e}") from e
                else:
                    last_exc = e
                    self.failed_calls += 1
                    logger.error(
                        "llm_api_error",
                        label=label,
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        error=str(e),
                        error_code=e.code,
                        exc_info=True,
                    )
                    raise LLMError(f"LLM API error (code {e.code}): {e}") from e

            except LLMResponseParseError as e:
                last_exc = e
                logger.error(
                    "llm_parse_error",
                    label=label,
                    attempt=attempt + 1,
                    exc_type=type(e).__name__,
                    error=str(e),
                    raw_text_snippet=raw_text[:500] if 'raw_text' in dir() else "<no response>",
                    exc_info=True,
                )
                if attempt < max_retries - 1:
                    delay = self._delay(attempt)
                    await asyncio.sleep(delay)
                else:
                    self.failed_calls += 1
                    raise

            except Exception as e:
                last_exc = e
                self.failed_calls += 1
                logger.error(
                    "llm_unexpected_error",
                    label=label,
                    attempt=attempt + 1,
                    exc_type=type(e).__name__,
                    error=str(e),
                    exc_info=True,
                )
                raise

        self.failed_calls += 1
        elapsed = int((time.time() - start) * 1000)
        logger.error(
            "llm_retry_exhausted",
            label=label,
            max_retries=max_retries,
            elapsed_ms=elapsed,
            last_exc_type=type(last_exc).__name__ if last_exc else None,
            last_exc_message=str(last_exc) if last_exc else None,
        )
        raise LLMRetryExhaustedError(
            f"LLM call failed after {max_retries} attempts ({elapsed}ms)",
            last_exception=last_exc,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @traceable(run_type="llm", name="llm_generate")
    async def generate(
        self,
        prompt: str,
        content: str | None = None,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
        model_name: str | None = None,
    ) -> LLMResponse:
        cfg = config or GenerationConfig(
            max_output_tokens=self._settings.VERTEX_MAX_OUTPUT_TOKENS,
            temperature=self._settings.VERTEX_TEMPERATURE,
            response_json=self._settings.VERTEX_RESPONSE_JSON,
        )
        parts: list[Any] = []
        if content:
            parts.append(f"{prompt}\n\nContent to process:\n{content}")
        else:
            parts.append(prompt)
        return await self._call_with_retry(parts, cfg, label, model_name=model_name)

    @traceable(run_type="llm", name="llm_generate_pdf", process_inputs=filter_trace_inputs)
    async def generate_from_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
        model_name: str | None = None,
    ) -> LLMResponse:
        cfg = config or GenerationConfig(
            max_output_tokens=self._settings.VERTEX_MAX_OUTPUT_TOKENS,
            temperature=self._settings.VERTEX_TEMPERATURE,
            response_json=self._settings.VERTEX_RESPONSE_JSON,
        )
        doc_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        return await self._call_with_retry([prompt, doc_part], cfg, label, model_name=model_name)

    async def health_check(self) -> dict[str, Any]:
        try:
            client = self._get_client()
            response = await client.aio.models.generate_content(
                model=self._settings.VERTEX_MODEL,
                contents="Respond with exactly: OK",
                config=types.GenerateContentConfig(
                    max_output_tokens=self._settings.VERTEX_HEALTH_CHECK_MAX_TOKENS,
                ),
            )
            return {
                "status": "healthy",
                "model": self._settings.VERTEX_MODEL,
                "location": self._settings.VERTEX_LOCATION,
                "response": response.candidates[0].content.parts[0].text.strip(),
            }
        except Exception as e:
            logger.error("vertex_health_check_failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    def get_model_version(self) -> str:
        return self._settings.VERTEX_MODEL

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_tokens": self.total_tokens,
            "success_rate": (self.successful_calls / self.total_calls) if self.total_calls else 0,
        }

    def reset_stats(self) -> None:
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_tokens = 0
