from __future__ import annotations

from app.core.config import Settings
from app.services.llm.base import BaseLLMClient


def create_llm_client(settings: Settings) -> BaseLLMClient:
    """
    Factory that returns the configured LLM client implementation.

    Supported providers: vertex, openai, google_studio.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "vertex":
        from app.services.llm.vertex import VertexLLMClient
        return VertexLLMClient(settings)

    if provider == "openai":
        from app.services.llm.openai_client import OpenAILLMClient
        return OpenAILLMClient(settings)

    if provider == "google_studio":
        from app.services.llm.google_studio import GoogleStudioLLMClient
        return GoogleStudioLLMClient(settings)

    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. "
        "Supported: vertex, openai, google_studio"
    )
