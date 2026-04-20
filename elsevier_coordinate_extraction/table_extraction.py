from __future__ import annotations

import io
from functools import lru_cache
from importlib import resources
from typing import List, Tuple

import pandas as pd
from lxml import etree

from elsevier_coordinate_extraction.types import TableMetadata


@lru_cache(maxsize=None)
def _load_stylesheet() -> etree.XSLT:
    """Load the Elsevier table extraction stylesheet."""
    stylesheet_path = resources.files(
        "elsevier_coordinate_extraction.stylesheets"
    ).joinpath("elsevier_table_extraction.xsl")
    with stylesheet_path.open("rb") as fh:
        xslt_doc = etree.parse(fh)
    return etree.XSLT(xslt_doc)


def extract_tables_from_article(payload: bytes) -> List[Tuple[TableMetadata, pd.DataFrame]]:
    """Transform ScienceDirect XML into DataFrames using the XSL stylesheet."""
    try:
        stylesheet = _load_stylesheet()
        document = etree.fromstring(payload)
        transformed = stylesheet(document)  # type: ignore[arg-type]
    except Exception:
        return []
    return _parse_extracted_tables(transformed.getroot())


def _parse_extracted_tables(root: etree._Element) -> List[Tuple[TableMetadata, pd.DataFrame]]:
    tables: List[Tuple[TableMetadata, pd.DataFrame]] = []
    for extracted_table in root.findall("extracted-table"):
        metadata = _build_metadata(extracted_table)
        html_table = extracted_table.find("transformed-table/table")
        if html_table is None:
            continue
        table_str = etree.tostring(html_table, encoding="unicode")
        kwargs = {}
        if not html_table.xpath(".//th"):
            kwargs["header"] = 0
        try:
            df = pd.read_html(
                io.StringIO(table_str), flavor="lxml", thousands=None, **kwargs
            )[0]
        except (ValueError, IndexError):
            continue
        tables.append((metadata, df))
    return tables


def _build_metadata(node: etree._Element) -> TableMetadata:
    def _text(tag: str) -> str | None:
        element = node.find(tag)
        if element is None:
            return None
        text = " ".join(element.itertext()).strip()
        return text or None

    references: list[str] = []
    ref_container = node.find("reference-sentences")
    if ref_container is not None:
        for sentence in ref_container.findall("sentence"):
            text = " ".join(sentence.itertext()).strip()
            if text:
                references.append(text)

    original = node.find("original-table/*")
    raw_xml = None
    if original is not None:
        raw_xml = etree.tostring(original, encoding="unicode")
    return TableMetadata(
        label=_text("table-label"),
        identifier=_text("table-id"),
        caption=_text("table-caption"),
        legend=_text("table-legend"),
        foot=_text("table-wrap-foot"),
        raw_xml=raw_xml,
        reference_sentences=references,
    )
