from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from app.core.logging import get_logger

logger = get_logger(__name__)

SCHEMAS_DIR = Path(__file__).parent / "schemas"

_SCHEMA_MAP: dict[str, Path] = {
    "capture_output": SCHEMAS_DIR / "capture_output.json",
    "metadata": SCHEMAS_DIR / "financial" / "metadata_schema.json",
    "period": SCHEMAS_DIR / "financial" / "period_schema.json",
    "statement": SCHEMAS_DIR / "financial" / "statement_schema.json",
    "notes": SCHEMAS_DIR / "financial" / "notes_schema.json",
}


class SchemaValidator:
    """JSON-schema validation for LLM outputs."""

    @staticmethod
    @lru_cache(maxsize=16)
    def _load(name: str) -> dict[str, Any]:
        path = _SCHEMA_MAP.get(name)
        if path is None or not path.exists():
            logger.warning("schema_not_found", name=name)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def load_raw_schema(cls, name: str) -> dict[str, Any]:
        """Return the raw JSON schema dict (used by prompt builders)."""
        return cls._load(name)

    @classmethod
    def validate_against_schema(
        cls,
        schema: dict[str, Any],
        data: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate *data* against the provided schema dict."""
        if not schema:
            return True, []

        errors: list[str] = []
        try:
            jsonschema.validate(instance=data, schema=schema)
            return True, []
        except jsonschema.ValidationError as e:
            errors.append(str(e.message))
            for ctx in e.context or []:
                errors.append(str(ctx.message))
        except jsonschema.SchemaError as e:
            errors.append(f"Schema error: {e.message}")
        return False, errors

    @classmethod
    def validate(cls, schema_name: str, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate *data* against the named schema.

        Returns:
            (is_valid, error_messages)
        """
        schema = cls._load(schema_name)
        if not schema:
            logger.warning("schema_skip_validation", name=schema_name)
            return True, []

        return cls.validate_against_schema(schema, data)
