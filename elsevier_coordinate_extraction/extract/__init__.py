"""Extraction module public API."""

from __future__ import annotations

from elsevier_coordinate_extraction.extract.text import (
    TextExtractionError,
    extract_text_from_article,
    format_article_text,
    save_article_text,
)

__all__ = [
    "TextExtractionError",
    "extract_text_from_article",
    "format_article_text",
    "save_article_text",
]
