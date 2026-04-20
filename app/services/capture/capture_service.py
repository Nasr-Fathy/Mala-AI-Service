from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from langsmith import traceable

from app.core.exceptions import SchemaValidationError
from app.core.logging import get_logger
from app.core.tracing import filter_trace_inputs
from app.services.llm.base import BaseLLMClient
from app.services.pdf.layout_service import LayoutService
from app.validation.schema_validator import SchemaValidator

logger = get_logger(__name__)

EXPERIMENT_DIR = Path(__file__).resolve().parents[3] / "experment"

PROMPT_VERSION = "v1.0"

_CAPTURE_PROMPT: str | None = None


def _get_capture_prompt() -> str:
    global _CAPTURE_PROMPT
    if _CAPTURE_PROMPT is None:
        schema = SchemaValidator.load_raw_schema("capture_output")
        schema_str = json.dumps(schema, indent=2)
        _CAPTURE_PROMPT = f"""You are an advanced AI specialized in OCR and extracting structured data from Arabic financial statements. 
Your task is to analyze the provided document, extract all raw text and tables accurately, and output the result STRICTLY matching the provided JSON schema.

CRITICAL: You MUST output the extracted data as a valid JSON instance. 
DO NOT output the schema itself. Use the following JSON schema ONLY as a strict blueprint/rule for your output format:

<json_schema>
{schema_str}
</json_schema>


CRITICAL INSTRUCTIONS (MUST FOLLOW):

1. NO NULL IN HEADERS: You must NEVER output `null` inside the `headers` array of any table. The schema strictly requires strings. 
   - If a column header is visually missing in the document, you MUST infer a logical name in Arabic. 
   - Use "البيان" for the item/description column.
   - Use "إيضاح" for the notes/references column.
   - If you cannot infer a name, use an empty string "" instead of `null`.

2. MANDATORY DOCUMENT FIELDS: 
   - "confidence": Provide an estimated OCR confidence score (0.0 - 1.0) for each page.
   - "title" (inside tables): Extract the clear title above each table (e.g., "قائمة المركز المالي").

3. FINANCIAL NUMBERS & NEGATIVES: 
   - Numbers inside brackets like `(٤٥,٦١٦,٩٣٠)` indicate NEGATIVE values. Output them as negative numbers (e.g., -45616930).
   - PAY EXTRA ATTENTION to Arabic numerals OCR. Do not confuse `١٢` (12) with `١٣` (13). Double-check the image carefully.

4. STRICT COLUMN ALIGNMENT & NOTE NUMBERS (CRITICAL): 
   - The "إيضاح" (Notes) column is extremely prone to vertical shifting. You MUST align the note number exactly with the corresponding account name horizontally. 
   - DO NOT shift note numbers to subtotal rows (e.g., "إجمالي الموجودات") unless there is a clear note number visually on that exact line.
   - If a cell is visually empty, output `null`. Do not shift adjacent columns left or right.

5. DO NOT DROP ROWS WITHOUT TEXT:
   - Sometimes financial statements have a row with only a number (e.g., a subtotal) and NO description text next to it. 
   - You MUST extract this row. Put an empty string `""` or `null` in the description column, and put the number in its correct year column. NEVER drop a row that contains financial values.

6. TEXT & LANGUAGE:
   - Extract ALL text from every page, preserving the natural reading order.
   - Preserve original Arabic text. Set "detected_language" to "ar".
   - Page numbers must be 1-indexed. Table IDs must be unique per page.
7. HORIZONTAL MAPPING & RTL ARABIC TABLES (FATAL ERROR PREVENTION):
   - Arabic tables are read Right-to-Left. 
   - The right-most number column strictly belongs to the right-most year header.
   - The left-most number column strictly belongs to the left-most year header.
   - DO NOT SWAP the columns. Verify visually: if the year 2024 is the right-column and 2023 is the left-column, you MUST map the right-side value to 2024 and the left-side value to 2023.  
8. TABLE IDS:
   - Table IDs must be unique within each page.
   - Use a simple sequential format like "t1", "t2", "t3", etc.
   - Restart numbering on each new page.
Return ONLY valid JSON. Do not include any explanations, introduction, or markdown formatting like ```json.
CRITICAL - NO ACCOUNTING HALLUCINATIONS: You are strictly an OCR extractor, NOT an auditor. DO NOT recalculate numbers, DO NOT infer missing rows to make math formulas work, and DO NOT standardize or rewrite accounting terminology. You MUST extract strictly the visible text exactly as it appears in the image. If a row has numbers but no text description, extract the numbers and leave the description as an empty string "". Do NOT invent descriptions.
"""  
    return _CAPTURE_PROMPT

class CaptureService:
    """
    Stage 1 -- Data Capture (OCR).

    Accepts PDF bytes, extracts text/tables via an LLM,
    validates the output, maps pages back to originals,
    and returns a self-contained dict.
    """

    SCHEMA_VERSION = "v1"

    def __init__(self, llm_client: BaseLLMClient) -> None:
        self._llm = llm_client

    @traceable(run_type="chain", name="capture_ocr", process_inputs=filter_trace_inputs)
    async def process(
        self,
        pdf_bytes: bytes,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        Run OCR extraction on *pdf_bytes*.

        Args:
            pdf_bytes: Raw PDF content.
            page_numbers: Optional 1-indexed pages to extract. ``None`` = all.

        Returns:
            Dict matching the capture output schema + metadata.
        """
        start = time.time()

        total_pages = LayoutService.get_page_count(pdf_bytes)

        if page_numbers is None:
            page_numbers = list(range(1, total_pages + 1))

        if len(page_numbers) < total_pages:
            extracted_pdf = LayoutService.extract_pages_to_bytes(pdf_bytes, page_numbers)
        else:
            extracted_pdf = pdf_bytes

        logger.info("capture_ocr_start", pages=page_numbers)

        response = await self._llm.generate_from_pdf(
            prompt=_get_capture_prompt(),
            pdf_bytes=extracted_pdf,
            label="capture_ocr",
        )

        ocr_output = response.content
        print("ocr_output", ocr_output)
        self._dump_raw_output("capture", ocr_output)

        is_valid, errors = SchemaValidator.validate("capture_output", ocr_output)
        if not is_valid:
            logger.warning("capture_schema_invalid", errors=errors)
            raise SchemaValidationError("OCR output failed schema validation", errors=errors)

        pages = ocr_output.get("pages", [])
        self._map_pages(pages, page_numbers)

        tables = ocr_output.get("tables", [])
        self._map_tables(tables, page_numbers)

        page_map = LayoutService.build_page_map(page_numbers)
        elapsed = int((time.time() - start) * 1000)

        return {
            "raw_text": ocr_output.get("raw_text", ""),
            "pages": pages,
            "tables": tables,
            "detected_language": ocr_output.get("detected_language"),
            "page_map": page_map,
            "processed_pages": page_numbers,
            "page_count": len(page_numbers),
            "is_schema_valid": True,
            "schema_version": self.SCHEMA_VERSION,
            "metadata": {
                "model": response.model,
                "prompt_version": PROMPT_VERSION,
                "processing_time_ms": elapsed,
                "attempt": response.attempt,
                "estimated_tokens": response.total_tokens,
            },
        }

    # ------------------------------------------------------------------
    # Raw output persistence
    # ------------------------------------------------------------------

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
    # Page / table mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_pages(pages: list[dict], page_numbers: list[int]) -> None:
        for idx, page in enumerate(pages):
            if idx < len(page_numbers):
                page["original_page_number"] = page_numbers[idx]
            else:
                page["original_page_number"] = page.get("page_number", idx + 1)

    @staticmethod
    def _map_tables(tables: list[dict], page_numbers: list[int]) -> None:
        for table in tables:
            page_idx = table.get("page", 1) - 1
            if 0 <= page_idx < len(page_numbers):
                table["original_page_number"] = page_numbers[page_idx]
            else:
                table["original_page_number"] = table.get("page", 1)
            original_page = table["original_page_number"]
            table["table_id"] = f"p{original_page}_{table.get('table_id', 't1')}"
