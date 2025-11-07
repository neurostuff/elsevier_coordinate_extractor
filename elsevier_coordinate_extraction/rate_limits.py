"""Rate-limit detection and backoff utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


@dataclass(frozen=True)
class RateLimitSnapshot:
    """Structured view over rate-limit response headers."""

    limit: int | None
    remaining: int | None
    reset_epoch: float | None

    def seconds_until_reset(self) -> float | None:
        """Return seconds remaining until reset, if known."""
        if self.reset_epoch is None:
            return None
        now = datetime.now(timezone.utc).timestamp()
        return max(self.reset_epoch - now, 0.0)

    def to_metadata(self) -> dict[str, float | int | None]:
        """Convert snapshot into serializable metadata."""
        return {
            "rate_limit_limit": self.limit,
            "rate_limit_remaining": self.remaining,
            "rate_limit_reset_epoch": self.reset_epoch,
        }


def get_retry_delay(response: httpx.Response) -> float | None:
    """Return a suggested delay (seconds) before retrying a request.

    Elsevier uses standard ``Retry-After`` headers. When the header is present
    it may be a number of seconds or an HTTP-date. If no explicit header is
    provided we attempt to derive a delay from ``X-RateLimit-Reset``.
    """

    snapshot = get_rate_limit_snapshot(response)
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            try:
                dt = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = (dt - now).total_seconds()
            return max(delta, 0.0)

    if snapshot.reset_epoch is not None:
        delay = snapshot.seconds_until_reset()
        if delay and delay > 0:
            return delay
    return None


def get_rate_limit_snapshot(response: httpx.Response) -> RateLimitSnapshot:
    """Collect structured rate-limit header information from a response."""

    def _parse_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _parse_float(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    limit = _parse_int(response.headers.get("X-RateLimit-Limit"))
    remaining = _parse_int(response.headers.get("X-RateLimit-Remaining"))
    reset_epoch = _parse_float(response.headers.get("X-RateLimit-Reset"))
    return RateLimitSnapshot(limit=limit, remaining=remaining, reset_epoch=reset_epoch)
