"""Text extraction from Elsevier XML articles."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Mapping

from lxml import etree

from elsevier_coordinate_extraction.types import ArticleContent

__all__ = [
    "TextExtractionError",
    "extract_text_from_article",
    "format_article_text",
    "save_article_text",
]


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
) -> dict[str, str | None]:
    """Return structured text content extracted from an Elsevier article.

    Parameters
    ----------
    article:
        Either an :class:`ArticleContent` instance or a raw XML payload of
        ``bytes``.

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
        transformed = stylesheet(document)
    except etree.XSLTApplyError as exc:
        msg = "XSLT transformation failed for article payload."
        raise TextExtractionError(msg) from exc

    root = transformed.getroot()
    return {
        "doi": _clean_doi(_extract_text(root, "doi")),
        "pii": _clean_field(_extract_text(root, "pii")),
        "title": _clean_field(_extract_text(root, "title")),
        "keywords": _clean_keywords(_extract_text(root, "keywords")),
        "abstract": _clean_block(_extract_text(root, "abstract")),
        "body": _clean_block(_extract_text(root, "body")),
    }


def format_article_text(extracted: Mapping[str, str | None]) -> str:
    """Compose a plain-text article document from extracted text fields."""

    return _compose_text_document(extracted)


def save_article_text(
    article: ArticleContent,
    directory: Path | str,
    *,
    stem: str | None = None,
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

    Returns
    -------
    pathlib.Path
        Full path to the written text file.
    """

    extracted = extract_text_from_article(article)
    destination_dir = Path(directory)
    destination_dir.mkdir(parents=True, exist_ok=True)
    file_stem = stem or _default_stem(article, extracted)
    destination = destination_dir / f"{file_stem}.txt"
    document = _compose_text_document(extracted)
    destination.write_text(document, encoding="utf-8")
    return destination


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
