from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

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


async def process_articles(
    records: List[Record],
    output_dir: Path,
    *,
    settings: Settings,
    skip_xml: bool = False,
    skip_text: bool = False,
    skip_tables: bool = False,
    skip_coordinates: bool = False,
    continue_on_error: bool = False,
    use_cache: bool = True,
    verbose: bool = False,
) -> Dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = FileCache(output_dir / ".cache") if use_cache else None

    downloaded_errors: List[Record] = []
    download_exceptions: List[Exception] = []
    skipped_records: List[Record] = []

    async def _progress_callback(
        record: Record,
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        if error is not None:
            downloaded_errors.append(record.copy())
            download_exceptions.append(error)
        elif article is None:
            skipped_records.append(record.copy())

    stats = {"success": 0, "failed": 0, "skipped": 0}

    download_bar = tqdm(total=len(records), desc="Downloading", unit="article")
    async with ScienceDirectClient(settings) as client:
        downloaded_articles = await download_articles(
            records,
            client=client,
            cache=cache,
            progress_callback=_progress_callback,
        )
    download_bar.close()

    extract_bar = tqdm(downloaded_articles, desc="Extracting", unit="article")
    for article in extract_bar:
        record = (
            article.metadata.get("identifier_lookup")
            or {"doi": article.doi}
        )
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
                files=files_written,
                error=None,
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
                files=files_written,
                error=str(exc),
                duration=duration,
            )
            append_error_entry(output_dir, record=record, error=exc)
            stats["failed"] += 1
            extract_bar.write(f"Error processing {record}: {exc}")
            if not continue_on_error:
                extract_bar.close()
                raise
    extract_bar.close()

    for record, error in zip(downloaded_errors, download_exceptions):
        append_manifest_entry(
            output_dir,
            record=record,
            status="failed",
            files=[],
            error=str(error),
            duration=0.0,
        )
        append_error_entry(output_dir, record=record, error=error)
        stats["failed"] += 1

    for record in skipped_records:
        append_manifest_entry(
            output_dir,
            record=record,
            status="skipped",
            files=[],
            error=None,
            duration=0.0,
        )
        stats["skipped"] += 1

    return stats
