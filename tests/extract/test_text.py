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


def test_extract_text_from_jats_payload() -> None:
    payload = b"""
    <article xmlns="http://jats.nlm.nih.gov">
      <front>
        <article-meta>
          <article-id pub-id-type="doi">10.1007/jats-001</article-id>
          <title-group>
            <article-title>JATS Example Title</article-title>
          </title-group>
          <kwd-group>
            <kwd>fmri</kwd>
            <kwd>coordinates</kwd>
          </kwd-group>
          <abstract>
            <p>Abstract sentence one.</p>
          </abstract>
        </article-meta>
      </front>
      <body>
        <sec>
          <p>Body sentence one.</p>
        </sec>
      </body>
    </article>
    """.strip()
    article = build_article_content(
        doi="10.1007/jats-001",
        payload=payload,
        content_type="application/xml",
        format="xml",
        metadata={"provider": "springer"},
    )
    extracted = extract_text_from_article(article)
    assert extracted["doi"] == "10.1007/jats-001"
    assert extracted["title"] == "JATS Example Title"
    assert extracted["abstract"] and "Abstract sentence one." in extracted["abstract"]
    assert extracted["body"] and "Body sentence one." in extracted["body"]
    assert extracted["keywords"] and "fmri" in extracted["keywords"]
