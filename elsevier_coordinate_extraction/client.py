"""Async ScienceDirect client built on httpx."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from . import rate_limits
from .settings import Settings

__all__ = ["ScienceDirectClient"]


class ScienceDirectClient:
    """Thin wrapper around httpx.AsyncClient with Elsevier defaults."""

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

    async def __aenter__(self) -> ScienceDirectClient:
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
        headers: dict[str, str] = {
            "X-ELS-APIKey": self._settings.api_key,
            "User-Agent": self._settings.user_agent,
        }
        if self._settings.insttoken:
            headers["X-ELS-Insttoken"] = self._settings.insttoken
        timeout = httpx.Timeout(self._settings.timeout)
        client_kwargs: dict[str, Any] = {
            "base_url": self._settings.base_url,
            "timeout": timeout,
            "headers": headers,
            "transport": self._transport,
            "http2": True,
        }
        if self._settings.use_proxy:
            proxy_value = self._settings.https_proxy or self._settings.http_proxy
            if proxy_value:
                client_kwargs["proxy"] = proxy_value
        else:
            client_kwargs["trust_env"] = False
        self._client = httpx.AsyncClient(**client_kwargs)

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
        while True:
            request_headers = {"Accept": accept} if accept else {}
            async with self._semaphore:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    headers=request_headers,
                )
            delay = rate_limits.get_retry_delay(response)
            if (
                delay is not None
                and response.status_code in {429, 500, 503}
                and attempt < self._max_retries
            ):
                await asyncio.sleep(delay)
                attempt += 1
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise exc
            return response
