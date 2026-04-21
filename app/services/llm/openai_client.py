from __future__ import annotations

import asyncio
import base64
import json
import random
import time
from typing import Any

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, APIConnectionError

from langsmith import traceable

from app.core.config import Settings
from app.core.exceptions import (
    LLMError,
    LLMResponseParseError,
    LLMRetryExhaustedError,
)
from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs
from app.services.llm.base import BaseLLMClient, GenerationConfig, LLMResponse
from app.services.llm.llm_finalize import finalize_llm_response

logger = get_logger(__name__)


class OpenAILLMClient(BaseLLMClient):
    """Async OpenAI client with exponential-backoff retry."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.total_tokens = 0

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._settings.OPENAI_API_KEY)
            logger.info("openai_client_initialized", model=self._settings.OPENAI_MODEL)
        return self._client

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        s = self._settings
        base = min(s.LLM_BASE_DELAY * (2 ** attempt), s.LLM_MAX_DELAY)
        jitter = random.uniform(0, base * s.LLM_JITTER_FACTOR)
        return base + jitter

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(f"Invalid JSON from LLM: {e}") from e

    # ------------------------------------------------------------------
    # Core generation loop
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        messages: list[dict[str, Any]],
        config: GenerationConfig,
        label: str,
        model_name: str | None = None,
    ) -> LLMResponse:
        self.total_calls += 1
        client = self._get_client()
        max_retries = self._settings.LLM_MAX_RETRIES
        last_exc: BaseException | None = None
        start = time.time()

        resolved_model = model_name or self._settings.OPENAI_MODEL

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "temperature": config.temperature,
        }
        if config.response_json:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            try:
                logger.info("llm_attempt", label=label, attempt=attempt + 1, max_retries=max_retries)

                response = await client.chat.completions.create(**kwargs)

                choice = response.choices[0]
                raw_text = choice.message.content or ""
                parsed = self._parse_json(raw_text)

                self.successful_calls += 1
                elapsed = int((time.time() - start) * 1000)
                model_name_resp = getattr(response, "model", None) or resolved_model

                out = finalize_llm_response(
                    provider="openai",
                    model_name=model_name_resp,
                    raw_vendor_response=response,
                    content=parsed,
                    raw_text=raw_text,
                    attempt=attempt + 1,
                    elapsed_ms=elapsed,
                    label=label,
                )
                ut = out.usage
                if ut is not None:
                    if ut.total_tokens is not None:
                        self.total_tokens += ut.total_tokens
                    else:
                        self.total_tokens += (ut.input_tokens or 0) + (ut.output_tokens or 0)

                logger.info("llm_success", label=label, elapsed_ms=elapsed)

                return out

            except (RateLimitError, APITimeoutError, APIConnectionError) as e:
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

            except APIError as e:
                if e.status_code and e.status_code >= 500:
                    last_exc = e
                    delay = self._delay(attempt)
                    logger.error(
                        "llm_retryable_error",
                        label=label,
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        status_code=e.status_code,
                        error=str(e),
                        delay_s=round(delay, 1),
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
                else:
                    self.failed_calls += 1
                    logger.error(
                        "llm_api_error",
                        label=label,
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        status_code=e.status_code,
                        error=str(e),
                        exc_info=True,
                    )
                    raise LLMError(f"OpenAI API error: {e}") from e

            except LLMResponseParseError as e:
                last_exc = e
                logger.error(
                    "llm_parse_error",
                    label=label,
                    attempt=attempt + 1,
                    exc_type=type(e).__name__,
                    error=str(e),
                    raw_text_snippet=raw_text[:500] if raw_text else "<empty>",
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
            max_output_tokens=self._settings.OPENAI_MAX_OUTPUT_TOKENS,
            temperature=self._settings.OPENAI_TEMPERATURE,
        )
        user_text = f"{prompt}\n\nContent to process:\n{content}" if content else prompt
        messages = [{"role": "user", "content": user_text}]
        return await self._call_with_retry(messages, cfg, label, model_name=model_name)

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
            max_output_tokens=self._settings.OPENAI_MAX_OUTPUT_TOKENS,
            temperature=self._settings.OPENAI_TEMPERATURE,
        )
        b64_pdf = base64.standard_b64encode(pdf_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "file",
                        "file": {
                            "filename": "document.pdf",
                            "file_data": f"data:application/pdf;base64,{b64_pdf}",
                        },
                    },
                ],
            }
        ]
        return await self._call_with_retry(messages, cfg, label, model_name=model_name)

    async def health_check(self) -> dict[str, Any]:
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self._settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": "Respond with exactly: OK"}],
                max_tokens=10,
            )
            return {
                "status": "healthy",
                "model": self._settings.OPENAI_MODEL,
                "response": (response.choices[0].message.content or "").strip(),
            }
        except Exception as e:
            logger.error("openai_health_check_failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    def get_model_version(self) -> str:
        return self._settings.OPENAI_MODEL

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
