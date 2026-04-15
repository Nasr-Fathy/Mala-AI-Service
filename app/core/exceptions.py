from __future__ import annotations

import traceback
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

_handler_logger = get_logger("app.core.exceptions")


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class AIServiceError(Exception):
    """Root exception for the AI microservice."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

class LLMError(AIServiceError):
    """LLM call failed."""
    error_code = "LLM_ERROR"


class LLMRetryExhaustedError(LLMError):
    """All LLM retries exhausted."""
    error_code = "LLM_RETRY_EXHAUSTED"

    def __init__(self, message: str, last_exception: BaseException | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.last_exception = last_exception


class LLMResponseParseError(LLMError):
    """LLM returned unparseable response."""
    error_code = "LLM_RESPONSE_PARSE_ERROR"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

class PDFError(AIServiceError):
    """PDF processing error."""
    status_code = 422
    error_code = "PDF_ERROR"


class InvalidPDFError(PDFError):
    error_code = "INVALID_PDF"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class SchemaValidationError(AIServiceError):
    """JSON schema validation of LLM output failed."""
    status_code = 422
    error_code = "SCHEMA_VALIDATION_ERROR"

    def __init__(self, message: str, errors: list[str] | None = None, **kw: Any) -> None:
        super().__init__(message, details={"validation_errors": errors or []}, **kw)
        self.errors = errors or []


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineError(AIServiceError):
    """Pipeline execution error."""
    error_code = "PIPELINE_ERROR"


class StepError(PipelineError):
    """A pipeline step failed."""
    error_code = "STEP_ERROR"

    def __init__(self, step_name: str, message: str, **kw: Any) -> None:
        super().__init__(message, details={"step": step_name}, **kw)
        self.step_name = step_name


class PassExecutionError(PipelineError):
    """A mapping pass failed."""
    error_code = "PASS_EXECUTION_ERROR"

    def __init__(
        self,
        message: str,
        pass_number: int,
        pass_name: str = "",
        cause: BaseException | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(message, details={"pass_number": pass_number, "pass_name": pass_name}, **kw)
        self.pass_number = pass_number
        self.pass_name = pass_name
        self.__cause__ = cause


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------

async def ai_service_error_handler(_request: Request, exc: AIServiceError) -> JSONResponse:
    _handler_logger.error(
        "ai_service_error",
        error_code=exc.error_code,
        status_code=exc.status_code,
        message=exc.message,
        details=exc.details,
        exc_type=type(exc).__name__,
        traceback=traceback.format_exc(),
        exc_info=True,
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    _handler_logger.error(
        "unhandled_exception",
        exc_type=type(exc).__name__,
        exc_message=str(exc),
        traceback=traceback.format_exc(),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": f"{type(exc).__name__}: {exc}",
        },
    )
