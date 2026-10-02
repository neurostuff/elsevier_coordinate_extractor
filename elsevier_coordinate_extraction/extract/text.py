"""Text extraction from Elsevier XML articles."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Mapping

import pandas as pd
from lxml import etree

from elsevier_coordinate_extraction.table_extraction import (
    extract_tables_from_article,
)
from elsevier_coordinate_extraction.types import ArticleContent, TableMetadata

__all__ = [
    "TextExtractionError",
    "extract_text_from_article",
    "format_article_text",
    "save_article_text",
]

# Left in the body by 'text_extraction.xsl' at the position of each table when
# tables are kept. The key is the table's `@id`, or its rank among tables in
# document order when it has none -- both sides (this module and the
# stylesheet) count preceding ce:table elements the same way.
_TABLE_PLACEHOLDER = re.compile(r"\[elsevier-table-([^\]]+)\]")


class TextExtractionError(RuntimeError):
    """Raised when text extraction from an Elsevier article fails."""


@lru_cache(maxsize=None)
def _load_text_stylesheet() -> etree.XSLT:
    """Load and cache the Elsevier text extraction stylesheet."""

    stylesheet_path = resources.files(
        "elsevier_coordinate_extraction.stylesheets"
    ).joinpath("text_extraction.xsl")
    try:
        with stylesheet_path.open("rb") as handle:
            xslt_doc = etree.parse(handle)
    except (OSError, etree.XMLSyntaxError) as exc:
        msg = "Failed to load text extraction stylesheet."
        raise TextExtractionError(msg) from exc
    return etree.XSLT(xslt_doc)


def extract_text_from_article(
    article: ArticleContent | bytes,
    preserve_cross_references: bool = True,
    keep_tables: bool = False,
) -> dict[str, str | None]:
    """Return structured text content extracted from an Elsevier article.

    Parameters
    ----------
    article:
        Either an :class:`ArticleContent` instance or a raw XML payload of
        ``bytes``.
    preserve_cross_references:
        If ``True`` then inline cross-reference text is retained in output.
        If ``False`` then cross-reference elements are removed entirely.
    keep_tables:
        If ``True``, each table is inserted in the body at the position where
        it appears in the article: its label, then its contents as
        tab-separated values, then its footer. If ``False``, tables are left
        out of the body (they remain available via
        :func:`extract_tables_from_article`).

    Raises
    ------
    TextExtractionError
        If the payload cannot be parsed or the XSLT transformation fails.
    """

    payload = (
        article.payload if isinstance(article, ArticleContent) else article
    )
    try:
        document = etree.fromstring(payload)
    except etree.XMLSyntaxError as exc:
        raise TextExtractionError("Article payload is not valid XML.") from exc

    stylesheet = _load_text_stylesheet()
    try:
        transformed = stylesheet(
            document,
            **{
                "preserve-crossrefs": etree.XSLT.strparam(
                    "true" if preserve_cross_references else "false"
                ),
                "keep-tables": etree.XSLT.strparam(
                    "true" if keep_tables else "false"
                ),
            },
        )
    except etree.XSLTApplyError as exc:
        msg = "XSLT transformation failed for article payload."
        raise TextExtractionError(msg) from exc

    root = transformed.getroot()
    body = _clean_block(_extract_text(root, "body"))
    if keep_tables and body:
        body = _insert_tables(body, payload)
    return {
        "doi": _clean_doi(_extract_text(root, "doi")),
        "pii": _clean_field(_extract_text(root, "pii")),
        "title": _clean_field(_extract_text(root, "title")),
        "keywords": _clean_keywords(_extract_text(root, "keywords")),
        "abstract": _clean_block(_extract_text(root, "abstract")),
        "body": body,
    }


def format_article_text(extracted: Mapping[str, str | None]) -> str:
    """Compose a plain-text article document from extracted text fields."""

    return _compose_text_document(extracted)


def save_article_text(
    article: ArticleContent,
    directory: Path | str,
    *,
    stem: str | None = None,
    preserve_cross_references: bool = True,
    keep_tables: bool = False,
) -> Path:
    """Extract article text and persist it as a ``.txt`` file on disk.

    Parameters
    ----------
    article:
        Article payload and metadata.
    directory:
        Directory where the text file should be written. The directory is
        created if necessary.
    stem:
        Optional file-name stem to use; defaults to a slug derived from the
        article identifier metadata.
    preserve_cross_references:
        If ``True`` then inline cross-reference text is retained in output.
        If ``False`` then those elements are removed entirely.
    keep_tables:
        If ``True``, tables are inserted into the body text at the position
        where they appear in the article. See :func:`extract_text_from_article`.

    Returns
    -------
    pathlib.Path
        Full path to the written text file.
    """

    extracted = extract_text_from_article(
        article,
        preserve_cross_references=preserve_cross_references,
        keep_tables=keep_tables,
    )
    destination_dir = Path(directory)
    destination_dir.mkdir(parents=True, exist_ok=True)
    file_stem = stem or _default_stem(article, extracted)
    destination = destination_dir / f"{file_stem}.txt"
    document = _compose_text_document(extracted)
    destination.write_text(document, encoding="utf-8")
    return destination


def _insert_tables(body: str, payload: bytes) -> str:
    """Replace the placeholders left in `body` by the tables' contents.

    A table goes in at its first placeholder. One with no placeholder -- a
    float nothing anchors -- is appended, so every parsed table is in the
    text. Placeholders for tables that could not be parsed are removed.
    """
    tables = _load_tables(payload)
    placed: set[str] = set()

    def _substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in placed:
            return ""
        placed.add(key)
        return tables.get(key, "")

    body = _TABLE_PLACEHOLDER.sub(_substitute, body)
    leftover = [text for key, text in tables.items() if key not in placed]
    return "\n".join([body.rstrip("\n") + "\n", *leftover]) if leftover else body


def _load_tables(payload: bytes) -> dict[str, str]:
    """Map each table's placeholder key to its formatted text.

    Keyed by the table's `@id` where present, else its rank among tables in
    document order -- matching the key `text_extraction.xsl` used for the
    placeholder.
    """
    tables: dict[str, str] = {}
    for position, (metadata, frame) in enumerate(extract_tables_from_article(payload)):
        key = metadata.identifier or str(position)
        try:
            tables[key] = _format_table(metadata, frame)
        except Exception:
            continue
    return tables


def _format_table(metadata: TableMetadata, frame: pd.DataFrame) -> str:
    """Render an extracted table as tab-separated values, with label/caption/footer.

    Unlike pubget's PMC schema, `ce:caption`/`ce:label` are stripped from the
    running text everywhere (not just inside tables), so they are included
    here rather than assumed to already be present in the body.
    """
    grid = frame.to_csv(sep="\t", index=False, lineterminator="\n").strip("\n")
    parts = [metadata.label, metadata.caption, grid, metadata.foot]
    table_text = "\n".join(part for part in parts if part)
    return f"{table_text}\n"


def _extract_text(root: etree._Element, tag: str) -> str | None:
    element = root.find(tag)
    if element is None:
        return None
    text = "".join(element.itertext())
    return text or None


def _clean_doi(value: str | None) -> str | None:
    cleaned = _clean_field(value)
    if cleaned and cleaned.lower().startswith("doi:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    return cleaned or None


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clean_block(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    cleaned_lines: list[str] = []
    blank_run = False
    for line in lines:
        if not line:
            if not blank_run:
                cleaned_lines.append("")
            blank_run = True
            continue
        cleaned_lines.append(line)
        blank_run = False
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or None


def _clean_keywords(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    keywords = []
    for line in normalized.split("\n"):
        keyword = " ".join(line.split())
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return "\n".join(keywords) or None


def _compose_text_document(extracted: Mapping[str, str | None]) -> str:
    parts: list[str] = []

    title = extracted.get("title")
    if title:
        parts.append(f"# {title}")

    metadata_lines: list[str] = []
    doi = extracted.get("doi")
    if doi:
        metadata_lines.append(f"DOI: {doi}")
    pii = extracted.get("pii")
    if pii:
        metadata_lines.append(f"PII: {pii}")
    if metadata_lines:
        parts.append("\n".join(metadata_lines))

    keywords = extracted.get("keywords")
    if keywords:
        parts.append(f"## Keywords\n\n{keywords}")

    abstract = extracted.get("abstract")
    if abstract:
        parts.append(f"## Abstract\n\n{abstract}")

    body = extracted.get("body")
    if body:
        parts.append(body)

    chunks = (
        part.strip()
        for part in parts
        if part and part.strip()
    )
    text = "\n\n".join(chunks)
    return f"{text}\n" if text else ""


def _default_stem(
    article: ArticleContent,
    extracted: Mapping[str, str | None],
) -> str:
    candidates = (
        article.doi,
        extracted.get("pii"),
        article.metadata.get("pii"),
        article.metadata.get("identifier"),
    )
    for candidate in candidates:
        slug = _sanitize_slug(candidate)
        if slug:
            return slug
    return "article"


def _sanitize_slug(value: str | None) -> str:
    if not value:
        return ""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    slug = slug.strip("._")
    return slug[:120]
