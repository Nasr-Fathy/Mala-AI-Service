from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.services.llm.base import BaseLLMClient, GenerationConfig, LLMResponse


# ---------------------------------------------------------------------------
# Fake LLM client used by all tests -- never hits Vertex AI
# ---------------------------------------------------------------------------


class FakeLLMClient(BaseLLMClient):
    """Deterministic LLM stub returning configurable JSON."""

    def __init__(self) -> None:
        self._responses: dict[str, dict[str, Any]] = {}
        self._default_response: dict[str, Any] = {"status": "ok"}
        self.calls: list[dict[str, Any]] = []

    def set_response(self, label: str, data: dict[str, Any]) -> None:
        self._responses[label] = data

    def set_default_response(self, data: dict[str, Any]) -> None:
        self._default_response = data

    async def generate(
        self,
        prompt: str,
        content: str | None = None,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append({"method": "generate", "label": label})
        data = self._responses.get(label, self._default_response)
        return LLMResponse(content=data, raw_text="{}", model="fake-model")

    async def generate_from_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        config: GenerationConfig | None = None,
        label: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"method": "generate_from_pdf", "label": label, "response_schema": response_schema}
        )
        data = self._responses.get(label, self._default_response)
        return LLMResponse(content=data, raw_text="{}", model="fake-model")

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "model": "fake-model"}

    def get_model_version(self) -> str:
        return "fake-model"

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_calls": len(self.calls),
            "successful_calls": len(self.calls),
            "failed_calls": 0,
            "total_tokens": 0,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        GOOGLE_CLOUD_PROJECT_ID="test-project",
        LLM_PROVIDER="vertex",
        ENVIRONMENT="development",
    )


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF (1-page) with sample text."""
    import io
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Sample financial statement text")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def sample_capture_output() -> dict[str, Any]:
    return {
        "raw_text": "Sample financial statement text",
        "pages": [
            {"page_number": 1, "text": "Sample financial statement text", "original_page_number": 1}
        ],
        "tables": [
            {
                "page": 1,
                "table_id": "t1",
                "headers": ["Item", "2024", "2023"],
                "rows": [["Revenue", "100000", "90000"]],
                "original_page_number": 1,
            }
        ],
        "detected_language": "en",
        "page_map": {"0": 1},
        "processed_pages": [1],
        "page_count": 1,
        "is_schema_valid": True,
        "schema_version": "v1",
        "metadata": {
            "model": "fake-model",
            "prompt_version": "v1.0",
            "processing_time_ms": 100,
            "attempt": 1,
            "estimated_tokens": 100,
        },
    }


@pytest_asyncio.fixture
async def async_client(fake_llm: FakeLLMClient) -> AsyncIterator[AsyncClient]:
    """
    Provide an httpx AsyncClient wired to the FastAPI app
    with the real LLM swapped for the fake.

    The ``fake_llm`` fixture is shared with the test function so
    tests can call ``fake_llm.set_response(...)`` *before* making
    HTTP requests.
    """
    from app.main import create_app
    from app.services.capture.capture_service import CaptureService
    from app.services.mapping.category_mapper import CategoryMapper
    from app.services.mapping.financial_mapper import FinancialMapperService
    from app.pipeline.registry import StepRegistry
    from app.pipeline.orchestrator import PipelineOrchestrator
    from app.pipeline.steps.capture_step import CaptureStep
    from app.pipeline.steps.mapping_step import MappingStep

    app = create_app()

    app.state.llm_client = fake_llm
    app.state.category_mapper = CategoryMapper()
    app.state.capture_service = CaptureService(fake_llm)
    app.state.mapper_service = FinancialMapperService(fake_llm, app.state.category_mapper)

    registry = StepRegistry()
    registry.register(CaptureStep(app.state.capture_service))
    registry.register(MappingStep(app.state.mapper_service))
    app.state.pipeline = PipelineOrchestrator(registry)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
