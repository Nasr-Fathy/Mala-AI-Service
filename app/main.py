from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AIServiceError,
    ai_service_error_handler,
    generic_error_handler,
)
from app.core.logging import get_logger, setup_logging
from app.core.tracing import configure_tracing
from app.middleware.request_id import RequestIDMiddleware
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.registry import StepRegistry
from app.pipeline.steps.capture_step import CaptureStep
from app.pipeline.steps.mapping_step import MappingStep
from app.services.capture.capture_service import CaptureService
from app.services.llm.factory import create_llm_client
from app.services.mapping.category_mapper import CategoryMapper
from app.services.mapping.financial_mapper import FinancialMapperService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown hook."""
    settings = get_settings()

    setup_logging(
        log_level=settings.LOG_LEVEL,
        json_format=settings.ENVIRONMENT != "development",
    )

    configure_tracing(
        api_key=settings.LANGSMITH_API_KEY,
        project=settings.LANGSMITH_PROJECT,
        endpoint=settings.LANGSMITH_ENDPOINT,
    )

    logger.info(
        "app_startup",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENVIRONMENT,
    )

    # -- LLM client --
    llm_client = create_llm_client(settings)
    app.state.llm_client = llm_client

    # -- Category mapper --
    cat_mapper = CategoryMapper(
        csv_path=settings.CATEGORY_MAPPER_CSV_PATH,
        remote_url=settings.CATEGORY_MAPPER_REMOTE_URL,
        use_remote=settings.CATEGORY_MAPPER_USE_REMOTE,
        cache_ttl=settings.CATEGORY_MAPPER_CACHE_TTL,
    )
    cat_mapper.load()
    app.state.category_mapper = cat_mapper

    # -- Services --
    capture_service = CaptureService(llm_client)
    app.state.capture_service = capture_service

    mapper_service = FinancialMapperService(llm_client, cat_mapper)
    app.state.mapper_service = mapper_service

    # -- Pipeline --
    registry = StepRegistry()
    registry.register(CaptureStep(capture_service))
    registry.register(MappingStep(mapper_service))
    pipeline = PipelineOrchestrator(registry)
    app.state.pipeline = pipeline

    logger.info("app_ready")
    yield  # ---------- application runs ----------

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # -- Middleware (outermost first) --
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # -- Exception handlers --
    app.add_exception_handler(AIServiceError, ai_service_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_error_handler)  # type: ignore[arg-type]

    # -- Routers --
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
