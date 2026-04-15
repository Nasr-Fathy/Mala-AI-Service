from __future__ import annotations

import io
from typing import Any

import fitz  # PyMuPDF

from app.core.exceptions import InvalidPDFError, PDFError
from app.core.logging import get_logger

logger = get_logger(__name__)


class LayoutService:
    """
    In-memory PDF page extraction and manipulation using PyMuPDF.

    All operations work on ``bytes`` -- no disk I/O.
    """

    @staticmethod
    def extract_pages_to_bytes(pdf_bytes: bytes, page_numbers: list[int]) -> bytes:
        """
        Create a new PDF containing only the requested pages.

        Args:
            pdf_bytes: Source PDF as bytes.
            page_numbers: 1-indexed page numbers to keep.

        Returns:
            bytes for the subset PDF.
        """
        if not page_numbers:
            raise PDFError("page_numbers list cannot be empty")

        try:
            source = fitz.open(stream=pdf_bytes, filetype="pdf")
        except fitz.FileDataError as e:
            raise InvalidPDFError(f"Invalid PDF data: {e}") from e

        try:
            total = len(source)
            zero_indexed = [p - 1 for p in page_numbers if 1 <= p <= total]
            if not zero_indexed:
                raise PDFError(
                    f"No valid pages to extract. Document has {total} pages, "
                    f"requested: {page_numbers}"
                )

            new_doc = fitz.open()
            for idx in zero_indexed:
                new_doc.insert_pdf(source, from_page=idx, to_page=idx)

            buf = io.BytesIO()
            new_doc.save(buf)
            result = buf.getvalue()
            new_doc.close()

            logger.info(
                "pages_extracted",
                extracted=len(zero_indexed),
                output_bytes=len(result),
            )
            return result
        except PDFError:
            raise
        except Exception as e:
            raise PDFError(f"PDF extraction error: {e}") from e
        finally:
            source.close()

    @staticmethod
    def get_page_count(pdf_bytes: bytes) -> int:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except fitz.FileDataError as e:
            raise InvalidPDFError(f"Invalid PDF: {e}") from e
        try:
            return len(doc)
        finally:
            doc.close()

    @staticmethod
    def build_page_map(original_page_numbers: list[int]) -> dict[str, int]:
        """Map extracted page index (str) -> original page number (int)."""
        return {str(i): p for i, p in enumerate(original_page_numbers)}

    @staticmethod
    def validate_pdf(pdf_bytes: bytes) -> dict[str, Any]:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            return {"is_valid": False, "error": str(e)}
        try:
            return {
                "is_valid": True,
                "page_count": len(doc),
                "is_encrypted": doc.is_encrypted,
                "needs_password": doc.needs_pass,
                "metadata": doc.metadata,
                "size_bytes": len(pdf_bytes),
            }
        except Exception as e:
            return {"is_valid": False, "error": str(e)}
        finally:
            doc.close()
