from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

import httpx
from tqdm import tqdm

from elsevier_coordinate_extraction.cache import FileCache
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.extract import extract_text_from_article
from elsevier_coordinate_extraction.extract.coordinates import (
    extract_coordinates,
)
from elsevier_coordinate_extraction.settings import Settings
from elsevier_coordinate_extraction.table_extraction import (
    extract_tables_from_article,
)
from elsevier_coordinate_extraction.types import ArticleContent

from .outputs import (
    append_error_entry,
    append_manifest_entry,
    create_article_directory,
    write_article_text,
    write_article_xml,
    write_coordinates,
    write_metadata,
    write_tables,
)


Record = Dict[str, str]


def _normalize_source(value: object) -> str | None:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"elsevier", "springer"}:
            return lowered
    return None


def _infer_source_from_error(
    error: BaseException | None,
    reason: str | None,
) -> str | None:
    if reason:
        if reason == "pmid_to_doi_unresolved" or reason.startswith("springer_"):
            return "springer"
        if reason.startswith("elsevier_") or reason == "not_found_404":
            return "elsevier"

    if isinstance(error, httpx.HTTPStatusError):
        request = error.request or getattr(error.response, "request", None)
        if request is not None:
            host = request.url.host or ""
            lowered = host.lower()
            if "springernature.com" in lowered:
                return "springer"
            if "elsevier.com" in lowered:
                return "elsevier"
    return None


async def process_articles(
    records: List[Record],
    output_dir: Path,
    *,
    settings: Settings,
    skip_xml: bool = False,
    skip_text: bool = False,
    skip_tables: bool = False,
    skip_coordinates: bool = False,
    continue_on_error: bool = True,
    use_cache: bool = True,
    verbose: bool = False,
) -> Dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = FileCache(output_dir / ".cache") if use_cache else None

    downloaded_errors: List[tuple[Record, Exception, str | None]] = []
    skipped_records: List[tuple[Record, str, str | None]] = []

    async def _progress_callback(
        record: Record,
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        download_bar.update(1)
        if error is not None:
            reason = getattr(error, "skip_reason", None)
            source = _infer_source_from_error(error, reason if isinstance(reason, str) else None)
            if isinstance(reason, str) and reason:
                skipped_records.append((record.copy(), reason, source))
            else:
                if isinstance(error, Exception):
                    downloaded_errors.append((record.copy(), error, source))
                else:
                    downloaded_errors.append((record.copy(), Exception(str(error)), source))
        elif article is None:
            skipped_records.append((record.copy(), "not_found_404", "elsevier"))

    stats = {"success": 0, "failed": 0, "skipped": 0}

    download_bar = tqdm(total=len(records), desc="Downloading", unit="article")
    async with ScienceDirectClient(settings) as client:
        downloaded_articles = await download_articles(
            records,
            client=client,
            cache=cache,
            settings=settings,
            progress_callback=_progress_callback,
        )
    download_bar.close()

    extract_bar = tqdm(downloaded_articles, desc="Extracting", unit="article")
    for article in extract_bar:
        record = (
            article.metadata.get("identifier_lookup")
            or {"doi": article.doi}
        )
        source = _normalize_source(article.metadata.get("provider"))
        start = time.monotonic()
        files_written: List[Path] = []
        try:
            article_dir = create_article_directory(output_dir, record)

            if not skip_xml:
                files_written.append(write_article_xml(article_dir, article))

            files_written.append(write_metadata(article_dir, article))

            if not skip_text:
                extracted = extract_text_from_article(article)
                files_written.append(
                    write_article_text(article_dir, extracted)
                )

            if not skip_tables:
                tables = list(extract_tables_from_article(article.payload))
                files_written.extend(write_tables(article_dir, tables))

            if not skip_coordinates:
                coordinates = extract_coordinates([article])
                files_written.append(
                    write_coordinates(article_dir, coordinates)
                )

            duration = time.monotonic() - start
            append_manifest_entry(
                output_dir,
                record=record,
                status="success",
                source=source,
                files=files_written,
                error=None,
                reason=None,
                duration=duration,
            )
            stats["success"] += 1
            if verbose:
                extract_bar.write(f"Processed {article.doi}")

        except Exception as exc:
            duration = time.monotonic() - start
            append_manifest_entry(
                output_dir,
                record=record,
                status="failed",
                source=source,
                files=files_written,
                error=str(exc),
                reason=None,
                duration=duration,
            )
            append_error_entry(output_dir, record=record, error=exc, source=source)
            stats["failed"] += 1
            extract_bar.write(f"Error processing {record}: {exc}")
            if not continue_on_error:
                extract_bar.close()
                raise
    extract_bar.close()

    for record, error, source in downloaded_errors:
        append_manifest_entry(
            output_dir,
            record=record,
            status="failed",
            source=source,
            files=[],
            error=str(error),
            reason=None,
            duration=0.0,
        )
        append_error_entry(output_dir, record=record, error=error, source=source)
        stats["failed"] += 1

    for record, reason, source in skipped_records:
        append_manifest_entry(
            output_dir,
            record=record,
            status="skipped",
            source=source,
            files=[],
            error=None,
            reason=reason,
            duration=0.0,
        )
        stats["skipped"] += 1

    return stats
