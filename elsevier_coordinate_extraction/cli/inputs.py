from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

_RECORD_KEYS = {"doi", "pmid"}


def _normalize_record(payload: Dict[str, str]) -> Dict[str, str]:
    normalized = {
        key: payload[key].strip()
        for key in _RECORD_KEYS
        if payload.get(key)
    }
    return normalized


def parse_text_file(path: Path, key: str) -> List[Dict[str, str]]:
    if key not in _RECORD_KEYS:
        raise ValueError(f"Unsupported identifier key: {key}")
    records: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            records.append({key: line})
    return records


def parse_pmids(value: str) -> List[Dict[str, str]]:
    path = Path(value)
    if path.exists():
        return parse_text_file(path, "pmid")
    pmids = [item.strip() for item in value.split(",") if item.strip()]
    return [{"pmid": pmid} for pmid in pmids]


def parse_dois(value: str) -> List[Dict[str, str]]:
    path = Path(value)
    if path.exists():
        return parse_text_file(path, "doi")
    dois = [item.strip() for item in value.split(",") if item.strip()]
    return [{"doi": doi} for doi in dois]


def parse_jsonl(path: Path) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:  # pragma: no cover
                raise ValueError(
                    f"Invalid JSON on line {line_num}: {exc}"
                ) from exc
            record = _normalize_record(payload)
            if not record:
                raise ValueError(f"Record on line {line_num} lacks doi/pmid")
            records.append(record)
    return records


def validate_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    validated = []
    for record in records:
        normalized = _normalize_record(record)
        if not normalized:
            raise ValueError(
                "Each record must contain at least a doi or pmid."
            )
        validated.append(normalized)
    return validated
