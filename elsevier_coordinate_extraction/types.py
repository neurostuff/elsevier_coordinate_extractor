"""Package-wide type definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class ArticleContent:
    """Raw article payload retrieved from ScienceDirect."""

    doi: str
    payload: bytes
    content_type: str
    format: str
    retrieved_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        """Return payload size in bytes."""
        return len(self.payload)

    def with_metadata(self, **updates: Any) -> ArticleContent:
        """Return a copy of the article with metadata values updated."""
        merged = {**self.metadata, **updates}
        return ArticleContent(
            doi=self.doi,
            payload=self.payload,
            content_type=self.content_type,
            format=self.format,
            retrieved_at=self.retrieved_at,
            metadata=merged,
        )


@dataclass(slots=True)
class TableMetadata:
    """Metadata describing a table extracted from an article."""

    label: str | None = None
    identifier: str | None = None
    caption: str | None = None
    legend: str | None = None
    foot: str | None = None
    raw_xml: str | None = None


def build_article_content(
    doi: str,
    payload: bytes,
    *,
    content_type: str,
    fmt: str,
    metadata: Mapping[str, Any] | None = None,
    retrieved_at: datetime | None = None,
) -> ArticleContent:
    """Utility for constructing `ArticleContent` with sensible defaults."""
    meta = dict(metadata or {})
    timestamp = retrieved_at or datetime.now(timezone.utc)
    return ArticleContent(
        doi=doi,
        payload=payload,
        content_type=content_type,
        format=fmt,
        retrieved_at=timestamp,
        metadata=meta,
    )
