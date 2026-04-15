"""Centralised LangSmith tracing configuration.

Call :func:`configure_tracing` once during application startup (before any
traced function is invoked) to activate tracing.  When the API key is empty
the ``@traceable`` decorators from ``langsmith`` become transparent no-ops,
so there is zero overhead in environments that do not use LangSmith.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tracing setup
# ---------------------------------------------------------------------------

def configure_tracing(
    *,
    api_key: str,
    project: str = "financial-ai-service",
    endpoint: str = "",
) -> None:
    """Activate LangSmith tracing by setting the required env vars.

    Must be called **before** the first traced function is invoked
    (typically during FastAPI lifespan startup).  When *api_key* is
    empty, tracing is silently disabled.
    """
    if not api_key:
        logger.info("langsmith_tracing_disabled", reason="LANGSMITH_API_KEY not set")
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project

    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    logger.info("langsmith_tracing_enabled", project=project)


def build_trace_metadata(
    *,
    environment: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build a standard metadata dict for ``langsmith_extra``.

    Usage at call sites::

        result = await service.process(
            data,
            langsmith_extra={
                "metadata": build_trace_metadata(
                    environment=settings.ENVIRONMENT,
                    file_name="report.pdf",
                ),
                "tags": ["capture"],
            },
        )
    """
    meta: dict[str, Any] = {"service": "financial-ai-service"}
    if environment:
        meta["environment"] = environment
    meta.update(extra)
    return meta


# ---------------------------------------------------------------------------
# Binary / file-data filtering for traces
# ---------------------------------------------------------------------------

def _should_strip_files() -> bool:
    from app.core.config import get_settings  # deferred to avoid circular import
    return not get_settings().LANGSMITH_INCLUDE_FILES


def _sanitize_value(value: Any) -> Any:
    """Recursively replace ``bytes`` with a human-readable placeholder."""
    if isinstance(value, bytes):
        return f"<binary: {len(value):,} bytes>"
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_sanitize_value(v) for v in value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _sanitize_value(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    return value


def filter_trace_inputs(inputs: dict) -> dict:
    """``process_inputs`` callback for ``@traceable``.

    When ``LANGSMITH_INCLUDE_FILES`` is *false* (the default), any ``bytes``
    values found anywhere in the inputs dict are replaced with a size
    placeholder so that PDFs and other binary blobs never reach LangSmith.
    """
    if not _should_strip_files():
        return inputs
    return _sanitize_value(inputs)


def filter_trace_outputs(outputs: Any) -> Any:
    """``process_outputs`` callback for ``@traceable``.

    Same logic as :func:`filter_trace_inputs` but applied to the return
    value of a traced function.
    """
    if not _should_strip_files():
        return outputs
    return _sanitize_value(outputs)
