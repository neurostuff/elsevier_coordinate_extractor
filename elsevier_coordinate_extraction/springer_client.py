"""Async Springer Open Access client built on httpx."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from . import rate_limits
from .settings import Settings

__all__ = ["SpringerOpenAccessClient"]


def _http2_enabled() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


class SpringerOpenAccessClient:
    """Thin wrapper around httpx.AsyncClient for Springer OA endpoints."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._client: httpx.AsyncClient | None = None
        concurrency = settings.concurrency or 1
        self._semaphore = asyncio.Semaphore(concurrency)

    async def __aenter__(self) -> SpringerOpenAccessClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """Perform an HTTP request and return the response."""
        return await self._request(method, path, params=params, accept=accept)

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a GET request expecting JSON."""
        response = await self.request(
            "GET",
            path,
            params=params,
            accept="application/json",
        )
        return response.json()

    async def get_xml(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        """Perform a GET request expecting XML."""
        response = await self.request(
            "GET",
            path,
            params=params,
            accept="application/xml",
        )
        return response.text

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        headers: dict[str, str] = {"User-Agent": self._settings.user_agent}
        timeout = httpx.Timeout(self._settings.timeout)
        client_kwargs: dict[str, Any] = {
            "base_url": self._settings.springer_base_url,
            "timeout": timeout,
            "headers": headers,
            "transport": self._transport,
            "http2": _http2_enabled(),
        }
        if self._settings.use_proxy:
            proxy_value = self._settings.https_proxy or self._settings.http_proxy
            if proxy_value:
                client_kwargs["proxy"] = proxy_value
        else:
            client_kwargs["trust_env"] = False
        self._client = httpx.AsyncClient(**client_kwargs)

    def _build_params(
        self,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not self._settings.springer_api_key:
            raise RuntimeError(
                "SPRINGER_API_KEY is required to query Springer Open Access API."
            )
        merged = dict(params or {})
        merged.setdefault("api_key", self._settings.springer_api_key)
        return merged

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        accept: str | None,
    ) -> httpx.Response:
        await self._ensure_client()
        assert self._client is not None
        attempt = 0
        request_params = self._build_params(params)
        while True:
            request_headers = {"Accept": accept} if accept else {}
            async with self._semaphore:
                response = await self._client.request(
                    method,
                    path,
                    params=request_params,
                    headers=request_headers,
                )
            delay = rate_limits.get_retry_delay(response)
            max_wait = self._settings.max_rate_limit_wait
            if (
                delay is not None
                and response.status_code == 429
                and max_wait is not None
                and delay > max_wait
            ):
                snapshot = rate_limits.get_rate_limit_snapshot(response)
                wait_seconds = snapshot.seconds_until_reset() or delay
                retry_after = response.headers.get("Retry-After")
                raise httpx.HTTPStatusError(
                    "Springer OpenAccess rate limit wait "
                    f"({wait_seconds:g}s) exceeds configured maximum ({max_wait:g}s). "
                    "Likely quota exhaustion. "
                    f"Retry-After={retry_after!r}, "
                    f"X-RateLimit-Limit={snapshot.limit}, "
                    f"X-RateLimit-Remaining={snapshot.remaining}, "
                    f"X-RateLimit-Reset={snapshot.reset_epoch}.",
                    request=response.request,
                    response=response,
                )
            if (
                delay is not None
                and response.status_code in {429, 500, 503}
                and attempt < self._max_retries
            ):
                await asyncio.sleep(delay)
                attempt += 1
                continue
            response.raise_for_status()
            return response
