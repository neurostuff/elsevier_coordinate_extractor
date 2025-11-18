from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from elsevier_coordinate_extraction.extract import format_article_text
from elsevier_coordinate_extraction.types import ArticleContent, TableMetadata

_RECORD_KEYS = {"doi", "pmid"}


def _sanitize_identifier(record: Dict[str, str]) -> str:
    doi = record.get("doi", "").strip()
    pmid = record.get("pmid", "").strip()
    if doi:
        clean = re.sub(r"^10\.", "", doi)
        clean = re.sub(r"[^\w\-.]", "_", clean)
        return clean or "article"
    if pmid:
        return pmid
    raise ValueError("Record must contain at least one identifier")


def create_article_directory(base_dir: Path, record: Dict[str, str]) -> Path:
    article_dir = base_dir / _sanitize_identifier(record)
    article_dir.mkdir(parents=True, exist_ok=True)
    return article_dir


def write_article_xml(article_dir: Path, article: ArticleContent) -> Path:
    target = article_dir / "article.xml"
    target.write_bytes(article.payload)
    return target


def write_article_text(
    article_dir: Path,
    extracted_text: dict[str, str | None],
) -> Path:
    target = article_dir / "text.txt"
    target.write_text(format_article_text(extracted_text), encoding="utf-8")
    return target


def write_metadata(article_dir: Path, article: ArticleContent) -> Path:
    target = article_dir / "metadata.json"
    payload = {
        "doi": article.doi,
        "retrieved_at": article.retrieved_at.isoformat(),
        "content_type": article.content_type,
        "format": article.format,
        "size_bytes": article.size,
        **article.metadata,
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def write_tables(
    article_dir: Path,
    tables: Iterable[Tuple[TableMetadata, pd.DataFrame]],
) -> list[Path]:
    tables_dir = article_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    written: List[Path] = []
    for idx, (metadata, df) in enumerate(tables, start=1):
        label = (
            metadata.identifier
            or metadata.label
            or metadata.caption
            or f"table_{idx}"
        )
        sanitized = re.sub(r"[^\w\-.]", "_", label.lower()).strip("_")
        filename = f"{idx:02d}_{sanitized or 'table'}.csv"
        target = tables_dir / filename
        df.to_csv(target, index=False)
        written.append(target)
    return written


def write_coordinates(article_dir: Path, coordinates: dict[str, Any]) -> Path:
    target = article_dir / "coordinates.json"
    target.write_text(json.dumps(coordinates, indent=2), encoding="utf-8")
    return target


def append_manifest_entry(
    output_dir: Path,
    *,
    record: Dict[str, str],
    status: str,
    files: list[Path],
    error: str | None,
    duration: float,
) -> None:
    manifest_path = output_dir / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "identifier": record,
        "status": status,
        "files": [str(path.relative_to(output_dir)) for path in files],
        "error": error,
        "duration_seconds": round(duration, 3),
    }
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def append_error_entry(
    output_dir: Path,
    *,
    record: Dict[str, str],
    error: Exception,
) -> None:
    errors_path = output_dir / "errors.jsonl"
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "identifier": record,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    with errors_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
