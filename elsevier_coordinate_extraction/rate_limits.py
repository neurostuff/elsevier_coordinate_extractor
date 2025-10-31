"""Rate-limit detection and backoff utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


def get_retry_delay(response: httpx.Response) -> float | None:
    """Return a suggested delay (seconds) before retrying a request.

    Elsevier uses standard ``Retry-After`` headers. When the header is present
    it may be a number of seconds or an HTTP-date. If no explicit header is
    provided we attempt to derive a delay from ``X-RateLimit-Reset``.
    """

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

    reset = response.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            reset_epoch = float(reset)
        except ValueError:
            return None
        now = datetime.now(timezone.utc).timestamp()
        delay = reset_epoch - now
        if delay > 0:
            return delay
    return None
