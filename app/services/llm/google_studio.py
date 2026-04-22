from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

import google.generativeai as genai
from google.api_core import exceptions as google_exc

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
from app.services.llm.base import BaseLLMClient, GenerationConfig, LLMResponse
from app.services.llm.llm_finalize import finalize_llm_response

logger = get_logger(__name__)


class GoogleStudioLLMClient(BaseLLMClient):
    """Async Google AI Studio (Gemini) client with exponential-backoff retry.

    Uses the ``google-generativeai`` SDK with an API key (no GCP project needed).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: genai.GenerativeModel | None = None
        self._initialized = False

        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_tokens = 0

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _ensure_init(self) -> None:
        if not self._initialized:
            genai.configure(api_key=self._settings.GOOGLE_AI_API_KEY)
            self._initialized = True
            logger.info(
                "google_studio_initialized",
                model=self._settings.GOOGLE_AI_MODEL,
            )

    def _get_model(self) -> genai.GenerativeModel:
        if self._model is None:
            self._ensure_init()
            self._model = genai.GenerativeModel(self._settings.GOOGLE_AI_MODEL)
        return self._model

    def _to_gen_config(self, cfg: GenerationConfig) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "max_output_tokens": cfg.max_output_tokens,
            "temperature": cfg.temperature,
        }
        if cfg.response_json:
            kw["response_mime_type"] = "application/json"
        return kw

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        s = self._settings
        base = min(s.LLM_BASE_DELAY * (2 ** attempt), s.LLM_MAX_DELAY)
        jitter = random.uniform(0, base * s.LLM_JITTER_FACTOR)
        return base + jitter

    # ------------------------------------------------------------------
    # Core generation loop (runs model.generate_content in a thread)
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        content_parts: list[Any],
        config: GenerationConfig,
        label: str,
        model_name: str | None = None,
    ) -> LLMResponse:
        self.total_calls += 1
        resolved_model = model_name or self._settings.GOOGLE_AI_MODEL
        if model_name:
            self._ensure_init()
            model = genai.GenerativeModel(resolved_model)
        else:
            model = self._get_model()
        gen_config = genai.GenerationConfig(**self._to_gen_config(config))
        max_retries = self._settings.LLM_MAX_RETRIES
        last_exc: BaseException | None = None
        start = time.time()

        for attempt in range(max_retries):
            try:
                logger.info("llm_attempt", label=label, attempt=attempt + 1, max_retries=max_retries)

                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: model.generate_content(
                        content_parts,
                        generation_config=gen_config,
                    ),
                )
                if not response.candidates:
                    raise LLMError("No response candidates from Gemini")

                raw_text = response.candidates[0].content.parts[0].text
                parsed = parse_llm_json(raw_text)

                self.successful_calls += 1
                elapsed = int((time.time() - start) * 1000)

                out = finalize_llm_response(
                    provider="google_genai",
                    model_name=resolved_model,
                    raw_vendor_response=response,
                    content=parsed,
                    raw_text=raw_text,
                    attempt=attempt + 1,
                    elapsed_ms=elapsed,
                    label=label,
                    content_parts=content_parts,
                )
                ut = out.usage
                if ut is not None:
                    if ut.total_tokens is not None:
                        self.total_tokens += ut.total_tokens
                    else:
                        self.total_tokens += (ut.input_tokens or 0) + (ut.output_tokens or 0)

                logger.info("llm_success", label=label, elapsed_ms=elapsed)

                return out

            except (google_exc.ResourceExhausted, google_exc.DeadlineExceeded, google_exc.ServiceUnavailable) as e:
                last_exc = e
                delay = self._delay(attempt)
                logger.error(
                    "llm_retryable_error",
                    label=label,
                    attempt=attempt + 1,
                    exc_type=type(e).__name__,
                    error=str(e),
                    delay_s=round(delay, 1),
                    exc_info=True,
                )
                await asyncio.sleep(delay)

            except google_exc.InvalidArgument as e:
                self.failed_calls += 1
                logger.error(
                    "llm_invalid_argument",
                    label=label,
                    attempt=attempt + 1,
                    exc_type=type(e).__name__,
                    error=str(e),
                    exc_info=True,
                )
                raise LLMError(f"Invalid LLM request: {e}") from e

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
            max_output_tokens=self._settings.GOOGLE_AI_MAX_OUTPUT_TOKENS,
            temperature=self._settings.GOOGLE_AI_TEMPERATURE,
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
            max_output_tokens=self._settings.GOOGLE_AI_MAX_OUTPUT_TOKENS,
            temperature=self._settings.GOOGLE_AI_TEMPERATURE,
        )

        pdf_part = {"mime_type": "application/pdf", "data": pdf_bytes}
        return await self._call_with_retry([prompt, pdf_part], cfg, label, model_name=model_name)

    async def health_check(self) -> dict[str, Any]:
        try:
            self._ensure_init()
            model = self._get_model()
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model.generate_content(
                    "Respond with exactly: OK",
                    generation_config=genai.GenerationConfig(max_output_tokens=10),
                ),
            )
            return {
                "status": "healthy",
                "model": self._settings.GOOGLE_AI_MODEL,
                "response": response.candidates[0].content.parts[0].text.strip(),
            }
        except Exception as e:
            logger.error("google_studio_health_check_failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    def get_model_version(self) -> str:
        return self._settings.GOOGLE_AI_MODEL

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
