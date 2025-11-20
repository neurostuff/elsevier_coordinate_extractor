"""Text extraction tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from elsevier_coordinate_extraction.extract import (
    TextExtractionError,
    extract_text_from_article,
    format_article_text,
    save_article_text,
)
from elsevier_coordinate_extraction.types import build_article_content


def _load_cassette_payload() -> bytes:
    cassette_path = (
        Path(__file__).parent.parent
        / "cassettes"
        / "test_extract_returns_coordinates_for_real_articles[doi].yaml"
    )
    with cassette_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    string_payload = data["interactions"][0]["response"]["body"]["string"]
    return string_payload.encode("utf-8")


def test_extract_text_from_real_article(tmp_path: Path) -> None:
    """Structured text should be extracted and persisted for real articles."""

    payload = _load_cassette_payload()
    article = build_article_content(
        doi="10.1016/j.nbd.2012.03.039",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={"pii": "S0969-9961(12)00128-3"},
    )
    extracted = extract_text_from_article(article)
    assert extracted["title"], "Expected article title to be present"
    assert extracted["body"], "Expected article body text to be present"

    formatted = format_article_text(extracted)
    output_dir = tmp_path / "articles"
    destination = save_article_text(article, output_dir)
    saved = destination.read_text(encoding="utf-8")
    assert destination.name.endswith(".txt")
    assert saved == formatted


def test_extract_text_invalid_payload() -> None:
    """Invalid XML payloads should raise a text extraction error."""

    with pytest.raises(TextExtractionError):
        extract_text_from_article(b"<not-xml>")
