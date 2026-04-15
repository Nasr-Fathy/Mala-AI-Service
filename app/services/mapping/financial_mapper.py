from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from langsmith import traceable

from app.core.exceptions import PassExecutionError
from app.core.logging import get_logger
from app.services.mapping.base_mapper import BaseMapperService
from app.services.mapping.prompts import (
    METADATA_EXTRACTION_PROMPT,
    NOTES_EXTRACTION_PROMPT,
    PERIOD_DETECTION_PROMPT,
    get_statement_prompt,
)

logger = get_logger(__name__)

EXPERIMENT_DIR = Path(__file__).resolve().parents[3] / "experment"


class FinancialMapperService(BaseMapperService):
    """
    Concrete mapper for financial-statement documents.

    Implements the four LLM passes with:
      - context-optimised Pass 3 (only relevant tables per statement)
      - parallelised Pass 3 via ``asyncio.gather``
    """

    @staticmethod
    def _dump_raw_output(name: str, data: dict) -> None:
        try:
            EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
            dest = EXPERIMENT_DIR / f"{name}.json"
            dest.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("raw_model_output_saved", function=name, path=str(dest))
        except Exception as exc:
            logger.warning("raw_model_output_save_failed", function=name, error=str(exc))

    # ------------------------------------------------------------------
    # Pass 1 -- Metadata
    # ------------------------------------------------------------------

    @traceable(run_type="chain", name="pass_1_metadata_extraction")
    async def _run_pass_1(self, ocr_data: dict) -> dict:
        try:
            filetr_ocr_data = {
                    key: value for key, value in ocr_data.items() 
                    if key not in ["tables", "pages"]
                }
            content = self._prepare_content(filetr_ocr_data)

            resp = await self._llm.generate(
                prompt=METADATA_EXTRACTION_PROMPT,
                content=content,
                label="pass1_metadata",
            )
            self._dump_raw_output("pass_1_metadata", resp.content)
            result = self._normalize_pass_1(resp.content)
            self._validate_pass(result, "metadata", 1)
            return result
        except PassExecutionError:
            logger.error("pass_1_failed", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                "pass_1_failed",
                exc_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise PassExecutionError("Metadata extraction failed", pass_number=1, pass_name="Metadata Extraction", cause=e) from e

    @staticmethod
    def _normalize_pass_1(result: dict) -> dict:
        audit = result.get("audit")
        if isinstance(audit, dict) and audit.get("is_audited") is None:
            audit["is_audited"] = False
        for period in result.get("fiscal_periods", []):
            if period.get("is_comparative") is None:
                period["is_comparative"] = False
        return result

    # ------------------------------------------------------------------
    # Pass 2 -- Segmentation
    # ------------------------------------------------------------------

    @traceable(run_type="chain", name="pass_2_period_detection")
    async def _run_pass_2(self, ocr_data: dict) -> dict:
        try:

            filetr_ocr_data = {
            "pages": ocr_data.get("pages", []),
            "tables": [
                {
                    "table_id": t.get("table_id"),
                    "title": t.get("title"),
                    "page": t.get("page"),
                    "headers": t.get("headers"),
                }
                for t in ocr_data.get("tables", [])
            ],
        }

            content = self._prepare_content(filetr_ocr_data)
            enhanced = {"ocr_data": json.loads(content)}
            resp = await self._llm.generate(
                prompt=PERIOD_DETECTION_PROMPT,
                content=json.dumps(enhanced, ensure_ascii=False, indent=2),
                label="pass2_segmentation",
            )
            result = resp.content
            print(result)
            self._dump_raw_output("pass_2_period_detection", result)
            self._validate_pass(result, "period", 2)
            return result
        except PassExecutionError:
            logger.error("pass_2_failed", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                "pass_2_failed",
                exc_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise PassExecutionError("Period detection failed", pass_number=2, pass_name="Period Detection", cause=e) from e

    # ------------------------------------------------------------------
    # Pass 3 -- Statement Structuring  (parallelised)
    # ------------------------------------------------------------------

    @traceable(run_type="chain", name="pass_3_statement_structuring")
    async def _run_pass_3(self, ocr_data: dict, pass_2: dict) -> dict:
        statements = pass_2.get("statements", [])
        non_notes = [s for s in statements if s.get("statement_type") != "NOTES"]

        if not non_notes:
            return {"statements": []}

        tasks = [self._process_statement(ocr_data, stmt) for stmt in non_notes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output_stmts: list[dict] = []
        for stmt_info, result in zip(non_notes, results):
            if isinstance(result, BaseException):
                stype = stmt_info.get("statement_type", "?")
                logger.error(
                    "pass_3_statement_failed",
                    statement_type=stype,
                    exc_type=type(result).__name__,
                    error=str(result),
                    exc_info=result,
                )
                raise PassExecutionError(
                    f"Statement structuring failed for {stype}",
                    pass_number=3,
                    pass_name=f"Statement Structuring ({stype})",
                    cause=result,
                ) from result
            result["statement_info"] = stmt_info
            output_stmts.append(result)

        return {"statements": output_stmts}

    @traceable(run_type="chain", name="pass_3_single_statement")
    async def _process_statement(self, ocr_data: dict, stmt_info: dict) -> dict:
        stype = stmt_info.get("statement_type", "UNKNOWN")
        start = stmt_info.get("start_page", 1)
        end = stmt_info.get("end_page", start)

        tables = self._tables_for_pages(ocr_data, start, end, stmt_info.get("table_ids", []))
        text = self._text_for_pages(ocr_data, start, end)

        content = json.dumps(
            {
                "statement_type": stype,
                "text": text,
                "tables": tables,
                "columns": stmt_info.get("columns", []),
            },
            ensure_ascii=False,
            indent=2,
        )

        prompt = get_statement_prompt(stype)

        resp = await self._llm.generate(
            prompt=prompt,
            content=content,
            label=f"pass3_{stype}",
        )
        result = resp.content
        self._dump_raw_output(f"pass_3_{stype}", result)
        self._validate_pass(result, "statement", 3)
        return result

    # ------------------------------------------------------------------
    # Pass 4 -- Notes
    # ------------------------------------------------------------------

    @traceable(run_type="chain", name="pass_4_notes_extraction")
    async def _run_pass_4(self, ocr_data: dict, pass_2: dict) -> dict:
        try:
            notes_section = pass_2.get("notes_section") or {}
            if not notes_section:
                logger.info("mapping_no_notes_section")
                return {"notes": [], "confidence": 0.0}

            start = notes_section.get("start_page")
            end = notes_section.get("end_page")

            if start is None or end is None:
                logger.info(
                    "mapping_notes_section_pages_missing",
                    notes_section=notes_section,
                )
                return {"notes": [], "confidence": 0.0}

            content = self._prepare_content(ocr_data, include_tables=True, page_range=(start, end))
            resp = await self._llm.generate(
                prompt=NOTES_EXTRACTION_PROMPT,
                content=content,
                label="pass4_notes",
            )
            result = resp.content
            self._dump_raw_output("pass_4_notes", result)
            self._validate_pass(result, "notes", 4)
            return result
        except PassExecutionError:
            logger.error("pass_4_failed", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                "pass_4_failed",
                exc_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise PassExecutionError("Notes extraction failed", pass_number=4, pass_name="Notes Extraction", cause=e) from e

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tables_for_pages(
        ocr_data: dict, start: int, end: int, extra_ids: list[str] | None = None
    ) -> list[dict]:
        extra = set(extra_ids or [])
        return [
            t
            for t in ocr_data.get("tables", [])
            if start <= t.get("original_page_number", t.get("page", 0)) <= end
            or t.get("table_id", "") in extra
        ]

    @staticmethod
    def _text_for_pages(ocr_data: dict, start: int, end: int) -> str:
        pages = ocr_data.get("pages", [])
        relevant = [
            p for p in pages
            if start <= p.get("original_page_number", p.get("page_number", 0)) <= end
        ]
        return "\n\n".join(p.get("text", "") for p in relevant)
