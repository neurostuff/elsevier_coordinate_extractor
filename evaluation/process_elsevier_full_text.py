"""Download Elsevier articles listed in the evaluation JSONL and check coordinates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from elsevier_coordinate_extraction.cache import FileCache
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.extract.coordinates import extract_coordinates
from elsevier_coordinate_extraction.settings import get_settings
from elsevier_coordinate_extraction.types import ArticleContent

INPUT_PATH = Path("evaluation/data/elsevier_full_text.jsonl")
OUTPUT_PATH = Path("evaluation/data/elsevier_missing_coordinates.jsonl")
CACHE_NAMESPACE = "science_direct_xml"


async def main() -> None:
    """Entrypoint for orchestrating article download and coordinate checking."""
    entries = list(_load_entries(INPUT_PATH))
    settings = get_settings()
    cache = FileCache(settings.cache_dir / CACHE_NAMESPACE)
    missing: list[dict[str, Any]] = []

    async with ScienceDirectClient(settings) as client:
        for index, entry in enumerate(entries, start=1):
            id_record = _identifier_record(entry)
            preferred_type = "doi" if "doi" in id_record else "pmid" if "pmid" in id_record else None
            preferred_identifier = id_record.get(preferred_type) if preferred_type else None
            status_prefix = f"[{index}/{len(entries)}]"
            if not id_record:
                reason = "no_identifier"
                missing.append(_missing_payload(entry, preferred_identifier, preferred_type, reason))
                print(f"{status_prefix} skipped: no identifier for entry {entry}")
                continue
            try:
                article = await _download_article(id_record, client, cache)
            except Exception as exc:  # noqa: BLE001
                reason = f"download_error: {exc}"
                missing.append(_missing_payload(entry, preferred_identifier, preferred_type, reason))
                print(f"{status_prefix} failed: {reason}")
                continue
            actual_identifier_type = article.metadata.get("identifier_type") or preferred_type or "unknown"
            actual_identifier = article.metadata.get("identifier") or preferred_identifier or article.doi
            if _has_coordinates(article):
                if index <= 10 or index % 100 == 0:
                    print(f"{status_prefix} ok: {actual_identifier_type}={actual_identifier}")
                continue
            reason = "no_coordinates_detected"
            missing.append(
                _missing_payload(entry, actual_identifier, actual_identifier_type, reason)
            )
            print(f"{status_prefix} missing coordinates for {actual_identifier_type}={actual_identifier}")

    _write_missing(OUTPUT_PATH, missing)
    print(f"Completed. Missing coordinates recorded at {OUTPUT_PATH} ({len(missing)} entries).")


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSONL not found: {path}")
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def _identifier_record(entry: dict[str, Any]) -> dict[str, str]:
    record: dict[str, str] = {}
    doi = entry.get("doi")
    pmid = entry.get("pmid")
    if doi:
        record["doi"] = doi
    if pmid:
        record["pmid"] = pmid
    return record


async def _download_article(
    identifier_record: dict[str, str],
    client: ScienceDirectClient,
    cache: FileCache,
) -> ArticleContent:
    articles = await download_articles(
        [identifier_record],
        client=client,
        cache=cache,
        cache_namespace=CACHE_NAMESPACE,
    )
    if not articles:
        raise RuntimeError("download_articles returned no payloads")
    return articles[0]


def _has_coordinates(article: ArticleContent) -> bool:
    result = extract_coordinates([article])
    studies = result.get("studyset", {}).get("studies", [])
    for study in studies:
        for analysis in study.get("analyses", []):
            if analysis.get("points"):
                return True
    return False


def _missing_payload(
    entry: dict[str, Any],
    identifier: str | None,
    identifier_type: str | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "doi": entry.get("doi"),
        "pmid": entry.get("pmid"),
        "identifier": identifier,
        "identifier_type": identifier_type,
        "reason": reason,
    }


def _write_missing(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
