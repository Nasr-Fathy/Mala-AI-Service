from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from langsmith import traceable

from app.core.exceptions import PassExecutionError
from app.core.logging import get_logger
from app.services.llm.base import BaseLLMClient, GenerationConfig
from app.services.mapping.base_mapper import BaseMapperService
from app.services.mapping.prompts import (
    METADATA_EXTRACTION_PROMPT,
    NOTES_EXTRACTION_PROMPT,
    PERIOD_DETECTION_PROMPT,
    get_statement_prompt,
)
from app.services.pdf.layout_service import LayoutService

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
    async def _run_pass_2(self, ocr_data: dict) -> dict:  # noqa: ARG002 – pass_1 reserved for future use
        try:

            filetr_ocr_data = {
            "pages": ocr_data.get("pages", []),
            "tables": [
                {
                    "table_id": t.get("table_id"),
                    "original_page_number": t.get("original_page_number"),
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
    async def _run_pass_3(
        self,
        ocr_data: dict,
        pass_1: dict,
        pass_2: dict,
        *,
        pdf_bytes: bytes | None = None,
    ) -> dict:
        statements = pass_2.get("statements", [])
        print(statements)
        non_notes = [s for s in statements if s.get("statement_type") != "NOTES"]

        if not non_notes:
            return {"statements": []}

        # valid_note_numbers = self._collect_note_numbers(ocr_data)

        tasks = [
            self._process_statement(
                ocr_data, stmt, pass_1,  pdf_bytes=pdf_bytes
            )
            for stmt in non_notes
        ]
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
            output_stmts.append({
            "statement": result,
            "statement_info": stmt_info
        })

        return {"statements": output_stmts}

    @traceable(run_type="chain", name="pass_3_single_statement")
    async def _process_statement(
        self,
        ocr_data: dict,
        stmt_info: dict,
        pass_1: dict,
        # valid_note_numbers: list[str],
        *,
        pdf_bytes: bytes | None = None,
    ) -> dict:
        stype = stmt_info.get("statement_type", "UNKNOWN")
        start = stmt_info.get("start_page", 1)
        end = stmt_info.get("end_page", start)

        raw_tables = self._tables_for_pages(
            ocr_data, start, end, stmt_info.get("table_ids", [])
        )
        tables = [self._trim_table(t) for t in raw_tables]
        pages_text = self._pages_text_for_range(ocr_data, start, end, stype)

        content = json.dumps(
            {
                "statement_type": stype,
                "statement_title": {
                    "en": stmt_info.get("title_en"),
                    "ar": stmt_info.get("title_ar"),
                },
                "page_range": {"start": start, "end": end},
                "currency": pass_1.get("currency", {}).get("code"),
                "value_scale": pass_1.get("value_scale", {}).get("multiplier", 1),
                "columns": stmt_info.get("columns", []),
                "tables": tables,
                "pages_text": pages_text,
            },
            ensure_ascii=False,
            indent=2,
        )
        print(content)

        prompt = get_statement_prompt(stype)
        config = GenerationConfig(max_output_tokens=32000,thinking_budget=3000,temperature=0.0, response_json=True, thinking_level="LOW")

        needs_image = self._needs_image(
            stype, stmt_info.get("columns", []), ocr_data, start, end, raw_tables
        )
        a=False
        if needs_image and pdf_bytes and a:
            page_numbers = list(range(start, end + 1))
            combined_prompt = f"{prompt}\n\nStructured data from OCR:\n{content}"
            try:
                sliced_pdf = LayoutService.extract_pages_to_bytes(pdf_bytes, page_numbers)
                resp = await self._llm.generate_from_pdf(
                    prompt=combined_prompt,
                    pdf_bytes=sliced_pdf,
                    config=config,
                    label=f"pass3_{stype}",
                )
            except Exception as exc:
                logger.warning(
                    "pass_3_image_fallback_failed, using text-only",
                    statement_type=stype,
                    error=str(exc),
                )
                resp = await self._llm.generate(
                    prompt=prompt,
                    content=content,
                    config=config,
                    label=f"pass3_{stype}",
                    
                )
        else:
            resp = await self._llm.generate(
                prompt=prompt,
                content=content,
                config=config,
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

        def page_num(t: dict) -> int:
            return t.get("original_page_number", t.get("page", 0))

        tables = [
            t for t in ocr_data.get("tables", [])
            if start <= page_num(t) <= end
        ]

        if extra:
            tables = [
                t for t in tables
                if t.get("table_id", "") in extra
            ]
            return tables


    # ------------------------------------------------------------------
    # Pass 3 helper methods
    # ------------------------------------------------------------------

    _BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"P\.O\.Box\s+\d+", re.IGNORECASE),
        re.compile(r"Tel\.\s*:", re.IGNORECASE),
        re.compile(r"Fax\s*:", re.IGNORECASE),
        re.compile(r"ص\.\s*ب\s*\d+", re.IGNORECASE),
        re.compile(r"هاتف\s*:", re.IGNORECASE),
        re.compile(r"فاكس\s*:", re.IGNORECASE),
        re.compile(r"الرمز البريدي\s*\d+", re.IGNORECASE),
        re.compile(r"Riyadh\s+\d+", re.IGNORECASE),
        re.compile(r"محاسبون ومراجعون قانونيون", re.IGNORECASE),
        re.compile(r"ترخيص رقم\s*\d+", re.IGNORECASE),
        re.compile(r"المجموعة السعودية للمحاسبة والمراجعة", re.IGNORECASE),
        re.compile(r"شركة المجموعة السعودية للمحاسبة", re.IGNORECASE),
    ]

    @classmethod
    def _strip_boilerplate(cls, text: str) -> str:
        lines = text.split("\n")
        filtered = [
            line for line in lines
            if not any(pat.search(line) for pat in cls._BOILERPLATE_PATTERNS)
        ]
        return "\n".join(filtered).strip()

    @staticmethod
    def _trim_table(table: dict) -> dict:
        return {
            "table_id": table.get("table_id"),
            "page": table.get("original_page_number", table.get("page")),
            "title": table.get("title"),
            "headers": table.get("headers"),
            "rows": table.get("rows"),
        }

    @classmethod
    def _pages_text_for_range(
        cls, ocr_data: dict, start: int, end: int, statement_type: str
    ) -> list[dict]:
        tabular_only = {"BALANCE_SHEET", "INCOME_STATEMENT"}
        if statement_type in tabular_only:
            return []

        pages = ocr_data.get("pages", [])
        relevant = [
            p for p in pages
            if start <= p.get("original_page_number", p.get("page_number", 0)) <= end
        ]
        out: list[dict] = []
        for p in relevant:
            pn = p.get("original_page_number", p.get("page_number", 0))
            text = cls._strip_boilerplate(p.get("text", ""))
            if text:
                out.append({"page": pn, "text": text})
        return out

    @staticmethod
    def _collect_note_numbers(ocr_data: dict) -> list[str]:
        seen: set[str] = set()
        for table in ocr_data.get("tables", []):
            headers = table.get("headers", [])
            note_col_idx: int | None = None
            for idx, h in enumerate(headers):
                if h and ("إيضاح" in h or "note" in h.lower()):
                    note_col_idx = idx
                    break
            if note_col_idx is None:
                for idx, h in enumerate(headers):
                    if h and h.strip() == "إيضاح":
                        note_col_idx = idx
                        break
            if note_col_idx is None:
                continue
            for row in table.get("rows", []):
                if note_col_idx < len(row):
                    val = row[note_col_idx]
                    if val is not None and str(val).strip():
                        seen.add(str(val).strip())
        return sorted(seen, key=lambda x: int(x) if x.isdigit() else x)

    _IMAGE_NEEDED_TYPES = {"CHANGES_IN_EQUITY", "CASH_FLOW"}
    _LOW_CONFIDENCE_THRESHOLD = 0.85
    _LARGE_TABLE_ROW_THRESHOLD = 30

    @classmethod
    def _needs_image(
        cls,
        statement_type: str,
        columns: list[dict],
        ocr_data: dict,
        start: int,
        end: int,
        tables: list[dict],
    ) -> bool:
        if statement_type in cls._IMAGE_NEEDED_TYPES:
            return True
        if not columns:
            return True
        pages = ocr_data.get("pages", [])
        relevant_pages = [
            p for p in pages
            if start <= p.get("original_page_number", p.get("page_number", 0)) <= end
        ]
        if relevant_pages:
            min_confidence = min(
                p.get("confidence", 1.0) for p in relevant_pages
            )
            if min_confidence < cls._LOW_CONFIDENCE_THRESHOLD:
                return True
        for t in tables:
            rows = t.get("rows", [])
            if len(rows) > cls._LARGE_TABLE_ROW_THRESHOLD:
                return True
        return False
