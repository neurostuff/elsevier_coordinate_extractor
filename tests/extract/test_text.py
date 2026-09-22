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


def test_extract_text_preserves_cross_reference_text() -> None:
    """Inline XML cross-reference text should be preserved in extracted body."""

    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <article xmlns='http://www.elsevier.com/xml/xocs/dtd'
        xmlns:ce='http://www.elsevier.com/xml/common/dtd'
        xmlns:dc='http://purl.org/dc/elements/1.1/'
        xmlns:dcterms='http://purl.org/dc/terms/'
        xmlns:ja='http://www.elsevier.com/xml/ja/dtd'>
      <dc:title>Test Article</dc:title>
      <ce:sections>
        <ce:section>
          <ce:para>
            Text before parentheses (
            <ce:cross-ref refid='bb0140'>Hankin et al., 2007</ce:cross-ref>
            ) after.
          </ce:para>
        </ce:section>
      </ce:sections>
    </article>"""

    article = build_article_content(
        doi="10.1016/test",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={"pii": "TEST"},
    )

    extracted = extract_text_from_article(article)
    assert extracted["body"] is not None
    assert "Hankin et al., 2007" in extracted["body"]
    assert "( )" not in extracted["body"]


def test_extract_text_can_strip_cross_reference_text() -> None:
    """Cross-reference elements can be removed when not requested."""

    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <article xmlns='http://www.elsevier.com/xml/xocs/dtd'
        xmlns:ce='http://www.elsevier.com/xml/common/dtd'
        xmlns:dc='http://purl.org/dc/elements/1.1/'
        xmlns:dcterms='http://purl.org/dc/terms/'
        xmlns:ja='http://www.elsevier.com/xml/ja/dtd'>
      <dc:title>Test Article</dc:title>
      <ce:sections>
        <ce:section>
          <ce:para>
            Keep text before (
            <ce:cross-ref refid='bb0140'>Hankin et al., 2007</ce:cross-ref>
            ) after.
          </ce:para>
        </ce:section>
      </ce:sections>
    </article>"""

    article = build_article_content(
        doi="10.1016/test",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={"pii": "TEST"},
    )

    extracted = extract_text_from_article(article, preserve_cross_references=False)
    assert extracted["body"] is not None
    assert "Hankin et al., 2007" not in extracted["body"]
    assert "(" in extracted["body"]
    assert ")" in extracted["body"]


def test_extract_text_can_keep_tables() -> None:
    """Tables can be inserted into the body at the position they appear."""

    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <article xmlns='http://www.elsevier.com/xml/xocs/dtd'
        xmlns:ce='http://www.elsevier.com/xml/common/dtd'
        xmlns:dc='http://purl.org/dc/elements/1.1/'
        xmlns:dcterms='http://purl.org/dc/terms/'
        xmlns:ja='http://www.elsevier.com/xml/ja/dtd'>
      <dc:title>Test Article</dc:title>
      <ce:sections>
        <ce:section>
          <ce:para>Before table.</ce:para>
          <ce:table id='tbl1'>
            <ce:label>Table 1</ce:label>
            <ce:caption><ce:simple-para>Peak coordinates.</ce:simple-para></ce:caption>
            <ce:tgroup>
              <ce:thead>
                <ce:row><ce:entry>Region</ce:entry><ce:entry>x</ce:entry></ce:row>
              </ce:thead>
              <ce:tbody>
                <ce:row><ce:entry>IFG</ce:entry><ce:entry>-42</ce:entry></ce:row>
              </ce:tbody>
            </ce:tgroup>
            <ce:table-foot>Note: values in mm.</ce:table-foot>
          </ce:table>
          <ce:para>After table.</ce:para>
        </ce:section>
      </ce:sections>
    </article>"""

    article = build_article_content(
        doi="10.1016/test",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={"pii": "TEST"},
    )

    extracted = extract_text_from_article(article, keep_tables=True)
    body = extracted["body"]
    assert body is not None
    assert "Before table." in body
    assert "After table." in body
    assert "Table 1" in body
    assert "Peak coordinates." in body
    assert "Region\tx" in body
    assert "IFG\t-42" in body
    assert "Note: values in mm." in body
    assert "[elsevier-table-" not in body


def test_extract_text_omits_tables_by_default() -> None:
    """Tables are left out of the body unless explicitly requested."""

    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <article xmlns='http://www.elsevier.com/xml/xocs/dtd'
        xmlns:ce='http://www.elsevier.com/xml/common/dtd'
        xmlns:dc='http://purl.org/dc/elements/1.1/'
        xmlns:dcterms='http://purl.org/dc/terms/'
        xmlns:ja='http://www.elsevier.com/xml/ja/dtd'>
      <dc:title>Test Article</dc:title>
      <ce:sections>
        <ce:section>
          <ce:para>Before table.</ce:para>
          <ce:table id='tbl1'>
            <ce:label>Table 1</ce:label>
            <ce:tgroup>
              <ce:tbody>
                <ce:row><ce:entry>IFG</ce:entry><ce:entry>-42</ce:entry></ce:row>
              </ce:tbody>
            </ce:tgroup>
          </ce:table>
          <ce:para>After table.</ce:para>
        </ce:section>
      </ce:sections>
    </article>"""

    article = build_article_content(
        doi="10.1016/test",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={"pii": "TEST"},
    )

    extracted = extract_text_from_article(article)
    body = extracted["body"]
    assert body is not None
    assert "Table 1" not in body
    assert "IFG" not in body
    assert "[elsevier-table-" not in body


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
