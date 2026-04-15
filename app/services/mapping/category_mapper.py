from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CATEGORY = "OTHER"


class CategoryMapper:
    """
    Maps line-item names to canonical financial fields using
    keyword / synonym matching (longest-match-first).

    Supports bilingual EN/AR matching with text normalisation.
    Data can be loaded from a local CSV file or a remote URL.
    """

    def __init__(
        self,
        csv_path: str = "",
        remote_url: str = "",
        use_remote: bool = False,
        cache_ttl: int = 3600,
    ) -> None:
        self._csv_path = csv_path
        self._remote_url = remote_url
        self._use_remote = use_remote
        self._cache_ttl = cache_ttl

        self._keywords: list[dict[str, Any]] = []
        self._canonical_fields: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._load_time: float | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Force (re-)load keywords."""
        self._loaded = False
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded and self._load_time and (time.time() - self._load_time) < self._cache_ttl:
            return

        csv_content: str | None = None

        if self._use_remote and self._remote_url:
            csv_content = self._fetch_remote()

        if csv_content is None and self._csv_path:
            csv_content = self._read_local()

        if csv_content is None:
            logger.warning("category_mapper_no_data")
            self._loaded = True
            return

        self._parse(csv_content)
        self._loaded = True
        self._load_time = time.time()
        logger.info(
            "category_mapper_loaded",
            keywords=len(self._keywords),
            fields=len(self._canonical_fields),
        )

    def _fetch_remote(self) -> str | None:
        try:
            resp = httpx.get(self._remote_url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning("category_mapper_remote_fail", error=str(e))
            return None

    def _read_local(self) -> str | None:
        path = Path(self._csv_path)
        if not path.exists():
            logger.warning("category_mapper_file_missing", path=str(path))
            return None
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, csv_content: str) -> None:
        keywords: list[dict[str, Any]] = []
        canonical: dict[str, dict[str, Any]] = {}

        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            field_name = (row.get("Canonical Field Name") or "").strip()
            if not field_name:
                continue

            main_level = (row.get("Main Level") or "").strip()
            section = (row.get("Section / Parent Hierarchy") or "").strip()
            position_tag = (row.get("Statement Level (Position Tag)") or "").strip()
            synonyms_en = (row.get("Synonyms (English)") or "").strip()
            synonyms_ar = (row.get("Synonyms (Arabic)") or "").strip()

            canonical[field_name] = {
                "canonical_field": field_name,
                "main_level": main_level,
                "section": section,
                "position_tag": position_tag,
            }

            base = {
                "canonical_field": field_name,
                "main_level": main_level,
                "section": section,
                "position_tag": position_tag,
            }

            keywords.append({
                **base,
                "keyword": field_name,
                "normalized": self.normalize(field_name.replace("_", " "), "en"),
                "lang": "en",
                "length": len(field_name),
            })

            for syn in self._split(synonyms_en):
                keywords.append({
                    **base,
                    "keyword": syn,
                    "normalized": self.normalize(syn, "en"),
                    "lang": "en",
                    "length": len(syn),
                })

            for syn in self._split(synonyms_ar):
                keywords.append({
                    **base,
                    "keyword": syn,
                    "normalized": self.normalize(syn, "ar"),
                    "lang": "ar",
                    "length": len(syn),
                })

        keywords.sort(key=lambda k: -k["length"])
        self._keywords = keywords
        self._canonical_fields = canonical

    @staticmethod
    def _split(s: str) -> list[str]:
        return [t.strip() for t in s.split(",") if t.strip()] if s else []

    # ------------------------------------------------------------------
    # Text normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(text: str, lang: str = "en") -> str:
        if not text:
            return ""
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        if lang == "ar":
            text = re.sub(r"[أإآء]", "ا", text)
            text = re.sub(r"ة", "ه", text)
            text = re.sub(r"ى", "ي", text)
            text = re.sub(r"ـ", "", text)
            text = re.sub(r"[\u064B-\u0652]", "", text)
        return text

    @staticmethod
    def detect_language(text: str) -> str:
        if not text:
            return "en"
        arabic = len(re.findall(r"[\u0600-\u06FF]", text))
        alpha = len(re.findall(r"[a-zA-Z\u0600-\u06FF]", text))
        if alpha == 0:
            return "en"
        return "ar" if arabic / alpha > 0.5 else "en"

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(self, name: str, main_level: str | None = None) -> dict[str, Any]:
        """Return best match with metadata, or a default ``OTHER`` entry."""
        self._ensure_loaded()

        if not name or not self._keywords:
            return self._default_result()

        lang = self.detect_language(name)
        norm = self.normalize(name, lang)

        for kw in self._keywords:
            if main_level and kw["main_level"] and kw["main_level"] != main_level:
                continue
            if kw["normalized"] in norm:
                coverage = len(kw["normalized"]) / len(norm) if norm else 0
                return {
                    "category": kw["canonical_field"],
                    "matched_keyword": kw["keyword"],
                    "main_level": kw["main_level"],
                    "section": kw["section"],
                    "position_tag": kw["position_tag"],
                    "confidence": min(0.5 + coverage * 0.5, 1.0),
                }

        return self._default_result()

    def categorize_items(
        self, line_items: list[dict[str, Any]], main_level: str | None = None
    ) -> list[dict[str, Any]]:
        """In-place annotate a list of line-item dicts with category fields."""
        self._ensure_loaded()
        for item in line_items:
            name = item.get("name_en") or item.get("name_ar") or ""
            result = self.match(name, main_level)
            item["category"] = result["category"]
            item["category_matched_keyword"] = result["matched_keyword"]
            item["category_confidence"] = result["confidence"]
        return line_items

    @staticmethod
    def _default_result() -> dict[str, Any]:
        return {
            "category": DEFAULT_CATEGORY,
            "matched_keyword": None,
            "main_level": None,
            "section": None,
            "position_tag": None,
            "confidence": 0.0,
        }

    @property
    def is_loaded(self) -> bool:
        return self._loaded and bool(self._keywords)
