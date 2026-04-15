from __future__ import annotations

from copy import deepcopy
from typing import Any


class ProviderSchemaAdapter:
    """Build provider-compatible response schemas from a canonical schema."""

    @classmethod
    def for_provider(cls, schema: dict[str, Any], provider: str) -> dict[str, Any]:
        p = (provider or "").strip().lower()
        if p == "vertex":
            return cls._adapt_for_vertex(schema)
        return deepcopy(schema)

    @classmethod
    def _adapt_for_vertex(cls, schema: dict[str, Any]) -> dict[str, Any]:
        # Work on a deep copy to keep canonical schema immutable.
        out = deepcopy(schema)
        out.pop("$schema", None)
        return cls._strip_unsupported_null_unions(out)

    @classmethod
    def _strip_unsupported_null_unions(cls, node: Any) -> Any:
        if isinstance(node, dict):
            rewritten = {k: cls._strip_unsupported_null_unions(v) for k, v in node.items()}

            # Vertex may reject "type": ["x", "null"] style declarations.
            t = rewritten.get("type")
            if isinstance(t, list) and "null" in t:
                non_null = [x for x in t if x != "null"]
                if len(non_null) == 1:
                    rewritten["type"] = non_null[0]
                elif len(non_null) > 1:
                    rewritten.pop("type", None)
                    rewritten["anyOf"] = [{"type": x} for x in non_null]
                else:
                    rewritten["type"] = "string"

            # Drop explicit null branches from oneOf/anyOf if present.
            for key in ("oneOf", "anyOf"):
                branch = rewritten.get(key)
                if isinstance(branch, list):
                    filtered = []
                    for option in branch:
                        option = cls._strip_unsupported_null_unions(option)
                        if isinstance(option, dict) and option.get("type") == "null":
                            continue
                        filtered.append(option)
                    if filtered:
                        rewritten[key] = filtered
                    else:
                        rewritten.pop(key, None)
            return rewritten

        if isinstance(node, list):
            return [cls._strip_unsupported_null_unions(x) for x in node]
        return node


class ProviderOutputNormalizer:
    """Normalize provider-specific output back to canonical schema semantics."""

    _NULL_SENTINELS = {"", "null", "none", "n/a", "na", "-", "—", "–"}

    @classmethod
    def normalize(cls, provider: str, data: Any, original_schema: dict[str, Any]) -> Any:
        p = (provider or "").strip().lower()
        if p == "vertex":
            return cls._normalize_vertex(data, original_schema)
        return cls._normalize_with_schema(data, original_schema)

    @classmethod
    def _normalize_vertex(cls, data: Any, original_schema: dict[str, Any]) -> Any:
        # Vertex structured-output may avoid nulls; restore canonical null semantics.
        return cls._normalize_with_schema(data, original_schema)

    @classmethod
    def _normalize_with_schema(cls, value: Any, schema: dict[str, Any] | None) -> Any:
        if schema is None:
            return value

        if cls._schema_allows_null(schema) and cls._is_null_like(value):
            return None

        if isinstance(value, dict):
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            out: dict[str, Any] = {}
            for k, v in value.items():
                child_schema = props.get(k) if isinstance(props, dict) else None
                out[k] = cls._normalize_with_schema(v, child_schema)
            return out

        if isinstance(value, list):
            item_schema = schema.get("items") if isinstance(schema, dict) else None
            return [cls._normalize_with_schema(item, item_schema) for item in value]

        return value

    @classmethod
    def _schema_allows_null(cls, schema: dict[str, Any]) -> bool:
        t = schema.get("type")
        if t == "null":
            return True
        if isinstance(t, list) and "null" in t:
            return True
        for key in ("anyOf", "oneOf"):
            branch = schema.get(key)
            if isinstance(branch, list):
                if any(isinstance(opt, dict) and cls._schema_allows_null(opt) for opt in branch):
                    return True
        return False

    @classmethod
    def _is_null_like(cls, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in cls._NULL_SENTINELS
        return False

