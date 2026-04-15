"""
Dependency-injection helpers for FastAPI endpoints.

All heavy objects (LLM client, services, pipeline orchestrator) are
created once during application lifespan and retrieved via ``app.state``.
"""
from __future__ import annotations

from fastapi import Request

from app.pipeline.orchestrator import PipelineOrchestrator
from app.services.capture.capture_service import CaptureService
from app.services.llm.base import BaseLLMClient
from app.services.mapping.category_mapper import CategoryMapper
from app.services.mapping.financial_mapper import FinancialMapperService


def get_llm_client(request: Request) -> BaseLLMClient:
    return request.app.state.llm_client


def get_capture_service(request: Request) -> CaptureService:
    return request.app.state.capture_service


def get_mapper_service(request: Request) -> FinancialMapperService:
    return request.app.state.mapper_service


def get_category_mapper(request: Request) -> CategoryMapper:
    return request.app.state.category_mapper


def get_pipeline(request: Request) -> PipelineOrchestrator:
    return request.app.state.pipeline
