from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "Financial AI Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8090
    WORKERS: int = 1

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["*"]

    # --- LLM Provider ---
    LLM_PROVIDER: Literal["vertex", "openai", "google_studio"] = "vertex"

    # --- Dynamic LLM Routing ---
    DEFAULT_LLM_PROVIDER: str = ""   # "" means fall back to LLM_PROVIDER
    DEFAULT_LLM_MODEL: str = ""      # "" means use the provider-specific default model
    TASK_LLM_OVERRIDES: str = "{}"   # JSON: '{"extraction":{"provider":"vertex","model":"gemini-2.5-pro"}}'

    # --- Vertex AI ---
    GOOGLE_CLOUD_PROJECT_ID: str = ""
    VERTEX_LOCATION: str = "us-central1"
    VERTEX_MODEL: str = "gemini-1.5-pro-002"
    VERTEX_MAX_OUTPUT_TOKENS: int = 8192
    VERTEX_TEMPERATURE: float = 0.1
    VERTEX_RESPONSE_JSON: bool = True
    VERTEX_USE_VERTEXAI: bool = True
    VERTEX_THINKING_BUDGET: int = 4096
    VERTEX_THINKING_BUDGET_MIN: int = 0
    VERTEX_THINKING_BUDGET_RETRY_MULTIPLIER: float = 0.5
    VERTEX_THINKING_LEVEL: str = ""
    VERTEX_HEALTH_CHECK_MAX_TOKENS: int = 10

    # --- OpenAI ---
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_MAX_OUTPUT_TOKENS: int = 8192
    OPENAI_TEMPERATURE: float = 0.1

    # --- Google AI Studio (Gemini via API key) ---
    GOOGLE_AI_API_KEY: str = ""
    GOOGLE_AI_MODEL: str = "gemini-1.5-pro"
    GOOGLE_AI_MAX_OUTPUT_TOKENS: int = 8192
    GOOGLE_AI_TEMPERATURE: float = 0.1

    # --- LLM Retry ---
    LLM_MAX_RETRIES: int = 5
    LLM_BASE_DELAY: float = 1.0
    LLM_MAX_DELAY: float = 60.0
    LLM_JITTER_FACTOR: float = 0.5

    # --- Category Mapper ---
    CATEGORY_MAPPER_CSV_PATH: str = ""
    CATEGORY_MAPPER_REMOTE_URL: str = ""
    CATEGORY_MAPPER_USE_REMOTE: bool = False
    CATEGORY_MAPPER_CACHE_TTL: int = 3600

    # --- LangSmith Tracing ---
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "financial-ai-service"
    LANGSMITH_ENDPOINT: str = ""
    LANGSMITH_INCLUDE_FILES: bool = False

    # --- API ---
    API_V1_PREFIX: str = "/api/v1"
    MAX_UPLOAD_SIZE_MB: int = 50

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
