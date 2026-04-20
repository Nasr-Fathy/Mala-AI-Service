from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from langsmith import traceable

from app.core.exceptions import PassExecutionError
from app.core.logging import get_logger
from app.services.llm.base import BaseLLMClient
from app.services.mapping.category_mapper import CategoryMapper
from app.validation.schema_validator import SchemaValidator

logger = get_logger(__name__)


class BaseMapperService(ABC):
    """
    Abstract base for all mapper implementations.

    Provides the multi-pass orchestration framework,
    schema validation helpers, and OCR content utilities.
    Subclasses implement the four pass methods.

    This class is designed to be **instantiated once** and shared across
    concurrent requests.  All per-request state lives in local variables
    inside ``process()`` -- never on ``self``.
    """

    PROMPT_VERSION = "v1.0"

    def __init__(
        self,
        llm_client: BaseLLMClient,
        category_mapper: CategoryMapper,
    ) -> None:
        self._llm = llm_client
        self._category_mapper = category_mapper

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @traceable(run_type="chain", name="financial_mapping")
    async def process(
        self,
        ocr_data: dict[str, Any],
        *,
        pdf_bytes: bytes | None = None,
        apply_categories: bool = True,
    ) -> dict[str, Any]:
        """
        Run the full 4-pass mapping pipeline.

        Args:
            ocr_data: Dict with ``raw_text``, ``pages``, ``tables``, ``detected_language``.
            pdf_bytes: Optional original PDF bytes for vision-enhanced passes.
            apply_categories: Whether to run keyword-based category assignment after Pass 3.

        Returns:
            Dict with ``pass_1_output`` … ``pass_4_output`` plus ``metadata``.
        """
        start_time = time.time()

        logger.info("mapping_start")

        pass_1 = await self._run_pass_1(ocr_data)
        pass_2 = await self._run_pass_2(ocr_data)
        pass_3 = await self._run_pass_3(ocr_data, pass_1, pass_2, pdf_bytes=pdf_bytes)

        if apply_categories:
            self._apply_categories(pass_3)

        pass_4 = await self._run_pass_4(ocr_data, pass_2)

        elapsed = int((time.time() - start_time) * 1000)

        non_notes = [
            s for s in pass_2.get("statements", [])
            if s.get("statement_type") != "NOTES"
        ]
        llm_call_count = 2 + len(non_notes) + (1 if pass_2.get("notes_section") else 0)

        logger.info("mapping_complete", elapsed_ms=elapsed, llm_calls=llm_call_count)

        return {
            "pass_1_output": pass_1,
            "pass_2_output": pass_2,
            "pass_3_outputs": pass_3,
            "pass_4_output": pass_4,
            "metadata": {
                "model": self._llm.get_model_version(),
                "prompt_version": self.PROMPT_VERSION,
                "processing_time_ms": elapsed,
                "total_llm_calls": llm_call_count,
            },
        }

    # ------------------------------------------------------------------
    # Abstract passes
    # ------------------------------------------------------------------

    @abstractmethod
    async def _run_pass_1(self, ocr_data: dict) -> dict:
        """Pass 1 -- Metadata Extraction."""

    @abstractmethod
    async def _run_pass_2(self, ocr_data: dict, pass_1: dict) -> dict:
        """Pass 2 -- Period Detection & Segmentation."""

    @abstractmethod
    async def _run_pass_3(
        self,
        ocr_data: dict,
        pass_1: dict,
        pass_2: dict,
        *,
        pdf_bytes: bytes | None = None,
    ) -> dict:
        """Pass 3 -- Statement Structuring (parallelisable)."""

    @abstractmethod
    async def _run_pass_4(self, ocr_data: dict, pass_2: dict) -> dict:
        """Pass 4 -- Notes Extraction."""

    # ------------------------------------------------------------------
    # Category assignment
    # ------------------------------------------------------------------

    def _apply_categories(self, pass_3_output: dict) -> None:
        for stmt in pass_3_output.get("statements", []):
            stmt_type = stmt.get("statement_type")
            line_items = stmt.get("line_items", [])
            self._category_mapper.categorize_items(line_items, main_level=stmt_type)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_pass(output: dict, schema_name: str, pass_number: int) -> None:
        ok, errors = SchemaValidator.validate(schema_name, output)
        if not ok:
            raise PassExecutionError(
                f"Pass {pass_number} output failed schema validation",
                pass_number=pass_number,
                pass_name=schema_name,
            )

    # ------------------------------------------------------------------
    # OCR content helpers
    # ------------------------------------------------------------------

   
    @staticmethod
    def _prepare_content(
        ocr_data: dict,
        *,
        include_tables: bool = True,
        page_range: tuple[int, int] | None = None,
    ) -> str:
        if page_range:
            start, end = page_range
            pages = [
                p for p in ocr_data.get("pages", [])
                if start <= p.get("original_page_number", p.get("page_number", 0)) <= end
            ]
            text = "\n\n".join(p.get("text", "") for p in pages)
            if include_tables:
                tables = [
                    t for t in ocr_data.get("tables", [])
                    if start <= t.get("original_page_number", t.get("page", 0)) <= end
                ]
            else:
                tables = []
        else:
            text = ocr_data.get("raw_text", "")
            tables = ocr_data.get("tables", []) if include_tables else []

        return json.dumps(
            {"text": text, "tables": tables, "detected_language": ocr_data.get("detected_language")},
            ensure_ascii=False,
            indent=2,
        )
