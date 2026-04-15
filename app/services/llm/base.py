from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.services.llm.token_usage import TokenUsage


@dataclass(frozen=True)
class GenerationConfig:
    """Vendor-agnostic generation configuration."""
    max_output_tokens: int = 8192
    temperature: float = 0.1
    response_json: bool = True


@dataclass
class LLMResponse:
    """Standardised wrapper around any LLM vendor response."""
    content: dict[str, Any]
    raw_text: str
    model: str
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    attempt: int = 1
    elapsed_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage | None = None

    @property
    def total_tokens(self) -> int:
        if self.usage is not None and self.usage.total_tokens is not None:
            return self.usage.total_tokens
        return self.estimated_input_tokens + self.estimated_output_tokens


class BaseLLMClient(ABC):
    """
    Vendor-agnostic async LLM client interface.

    Implementations must provide:
      - generate()          for text-only prompts
      - generate_from_pdf() for multimodal (PDF) prompts
      - health_check()      for readiness probing
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        content: str | None = None,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send a text prompt (with optional supporting content) and return parsed JSON."""

    @abstractmethod
    async def generate_from_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send a multimodal prompt with an inline PDF and return parsed JSON."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return health status of the underlying LLM backend."""

    @abstractmethod
    def get_model_version(self) -> str:
        """Return the identifier of the model being used."""
