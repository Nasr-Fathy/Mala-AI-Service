from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.llm.base import BaseLLMClient, GenerationConfig, LLMResponse

logger = get_logger(__name__)

_PROVIDER_MODULES: dict[str, str] = {
    "vertex": "app.services.llm.vertex.VertexLLMClient",
    "openai": "app.services.llm.openai_client.OpenAILLMClient",
    "google_studio": "app.services.llm.google_studio.GoogleStudioLLMClient",
}

# Map (provider) -> the Settings attribute that holds the default model name.
_DEFAULT_MODEL_ATTR: dict[str, str] = {
    "vertex": "VERTEX_MODEL",
    "openai": "OPENAI_MODEL",
    "google_studio": "GOOGLE_AI_MODEL",
}


class LLMRouter(BaseLLMClient):
    """Provider-agnostic LLM router that delegates to concrete provider clients.

    Supports a three-tier fallback chain for provider/model resolution:
        1. Explicit per-call ``provider`` / ``model_name`` arguments
        2. Task mapping via ``TASK_LLM_OVERRIDES`` from settings
        3. Settings defaults (``DEFAULT_LLM_PROVIDER`` / ``LLM_PROVIDER`` + provider model)

    Implements ``BaseLLMClient`` so it is a drop-in replacement wherever a single
    ``BaseLLMClient`` was used before.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, BaseLLMClient] = {}

        # Parse task mapping once at construction.
        raw = settings.TASK_LLM_OVERRIDES or "{}"
        try:
            self._task_mapping: dict[str, dict[str, str]] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("task_llm_overrides_invalid_json", raw=raw[:200])
            self._task_mapping = {}

        # Eagerly create the default provider client (same as pre-refactor).
        default_provider = self._effective_default_provider()
        self._clients[default_provider] = self._create_client(default_provider)

        logger.info(
            "llm_router_initialized",
            default_provider=default_provider,
            task_mapping_keys=list(self._task_mapping.keys()),
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _effective_default_provider(self) -> str:
        return (self._settings.DEFAULT_LLM_PROVIDER
                or self._settings.LLM_PROVIDER).lower()

    def _effective_default_model(self, provider: str) -> str:
        if self._settings.DEFAULT_LLM_MODEL:
            return self._settings.DEFAULT_LLM_MODEL
        attr = _DEFAULT_MODEL_ATTR.get(provider)
        if attr:
            return getattr(self._settings, attr, "")
        return ""

    def resolve_target(
        self,
        task_type: str | None = None,
        provider: str | None = None,
        model_name: str | None = None,
    ) -> tuple[BaseLLMClient, str]:
        """Resolve the concrete client and model for a call.

        Fallback chain:
            1. explicit per-call ``provider`` / ``model_name``
            2. task mapping from ``TASK_LLM_OVERRIDES``
            3. settings defaults
        """
        # Tier 1: explicit per-call override
        if provider:
            resolved_provider = provider.lower()
            resolved_model = model_name or self._effective_default_model(resolved_provider)
            return self._get_or_create(resolved_provider), resolved_model

        # Tier 2: task mapping
        if task_type and task_type in self._task_mapping:
            mapping = self._task_mapping[task_type]
            resolved_provider = mapping.get("provider", self._effective_default_provider()).lower()
            resolved_model = mapping.get("model") or self._effective_default_model(resolved_provider)
            return self._get_or_create(resolved_provider), resolved_model

        # Tier 3: settings defaults
        resolved_provider = self._effective_default_provider()
        resolved_model = model_name or self._effective_default_model(resolved_provider)
        return self._get_or_create(resolved_provider), resolved_model

    # ------------------------------------------------------------------
    # Client factory / registry
    # ------------------------------------------------------------------

    def _create_client(self, provider: str) -> BaseLLMClient:
        module_path = _PROVIDER_MODULES.get(provider)
        if not module_path:
            raise ValueError(
                f"Unsupported LLM provider: {provider!r}. "
                f"Supported: {', '.join(_PROVIDER_MODULES)}"
            )

        module_name, class_name = module_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        return cls(self._settings)

    def _get_or_create(self, provider: str) -> BaseLLMClient:
        if provider not in self._clients:
            self._clients[provider] = self._create_client(provider)
            logger.info("llm_provider_lazy_init", provider=provider)
        return self._clients[provider]

    # ------------------------------------------------------------------
    # BaseLLMClient interface (delegates to resolved client)
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        content: str | None = None,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
        model_name: str | None = None,
        # Router-specific kwargs for per-call routing:
        provider: str | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        client, resolved_model = self.resolve_target(
            task_type=task_type,
            provider=provider,
            model_name=model_name,
        )
        return await client.generate(
            prompt, content,
            config=config,
            label=label,
            response_schema=response_schema,
            model_name=resolved_model,
        )

    async def generate_from_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
        model_name: str | None = None,
        # Router-specific kwargs for per-call routing:
        provider: str | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        client, resolved_model = self.resolve_target(
            task_type=task_type,
            provider=provider,
            model_name=model_name,
        )
        return await client.generate_from_pdf(
            prompt, pdf_bytes,
            config=config,
            label=label,
            response_schema=response_schema,
            model_name=resolved_model,
        )

    async def health_check(self) -> dict[str, Any]:
        default_provider = self._effective_default_provider()
        client = self._get_or_create(default_provider)
        return await client.health_check()

    def get_model_version(self) -> str:
        default_provider = self._effective_default_provider()
        client = self._get_or_create(default_provider)
        return client.get_model_version()
