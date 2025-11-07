"""Tests for the ScienceDirect HTTP client."""

from __future__ import annotations

from typing import Any

import time

import httpx
import pytest

from elsevier_coordinate_extraction import settings
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.settings import Settings


_WAIT_SENTINEL: object = object()


def _make_test_settings(
    base_url: str = "https://example.test",
    *,
    max_wait: float | None | object = _WAIT_SENTINEL,
) -> Settings:
    """Create a Settings instance tailored for tests."""
    cfg = settings.get_settings()
    resolved_wait: float | None
    if max_wait is _WAIT_SENTINEL:
        resolved_wait = cfg.max_rate_limit_wait
    else:
        resolved_wait = max_wait  # type: ignore[assignment]
    return Settings(
        api_key="test-key",
        base_url=base_url,
        timeout=cfg.timeout,
        concurrency=cfg.concurrency,
        cache_dir=cfg.cache_dir,
        user_agent="TestClient/0.0.0",
        insttoken=None,
        http_proxy=None,
        https_proxy=None,
        use_proxy=False,
        max_rate_limit_wait=resolved_wait,
    )


@pytest.mark.asyncio()
async def test_client_injects_headers() -> None:
    """Client must attach the Elsevier API key and user agent to requests."""
    captured_headers: httpx.Headers | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_headers
        captured_headers = request.headers
        payload: dict[str, Any] = {"ok": True}
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(_make_test_settings(), transport=transport) as client:
        response = await client.get_json("/ping")
    assert response["ok"] is True
    assert captured_headers is not None
    assert captured_headers.get("X-ELS-APIKey") == "test-key"
    assert captured_headers.get("User-Agent") == "TestClient/0.0.0"
    assert captured_headers.get("Accept") == "application/json"
    assert "X-ELS-Insttoken" not in captured_headers


@pytest.mark.asyncio()
async def test_client_handles_http_error() -> None:
    """Non-successful responses should raise for status."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(_make_test_settings(), transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_json("/ping")


@pytest.mark.asyncio()
@pytest.mark.vcr()
async def test_client_fetches_search_results() -> None:
    """Integration test against ScienceDirect search endpoint."""

    cfg = settings.get_settings()
    async with ScienceDirectClient(cfg) as client:
        try:
            data = await client.get_json(
                "/search/sciencedirect",
                params={
                    "query": "TITLE(fmri)",
                    "count": "1",
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                pytest.skip("ScienceDirect credentials unavailable for test run.")
            raise
    assert "search-results" in data
    entries = data["search-results"].get("entry", [])
    assert isinstance(entries, list)
    if entries:
        first = entries[0]
        assert "dc:title" in first


@pytest.mark.asyncio()
async def test_client_can_disable_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """When proxy usage is disabled, trust_env should be False and no proxy set."""

    captured_kwargs: dict[str, Any] = {}

    class DummyAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        async def aclose(self) -> None:
            return None

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            request = httpx.Request(
                method,
                f"https://example.test{path}",
                params=params,
                headers=headers,
            )
            return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setenv("HTTP_PROXY", "socks5://localhost:1080")
    monkeypatch.setenv("HTTPS_PROXY", "socks5://localhost:1080")
    monkeypatch.setattr(
        "elsevier_coordinate_extraction.client.httpx.AsyncClient",
        DummyAsyncClient,
    )

    async with ScienceDirectClient(_make_test_settings()) as client:
        result = await client.get_json("/ping")
    assert result["ok"] is True
    assert captured_kwargs.get("trust_env") is False
    assert "proxy" not in captured_kwargs


@pytest.mark.asyncio()
async def test_client_retries_within_wait_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Client should retry when the wait duration does not exceed configured maximum."""

    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            headers = {
                "Retry-After": "0.05",
                "X-RateLimit-Reset": str(int(time.time()) + 1),
            }
            return httpx.Response(429, headers=headers, json={"error": "limit"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    transport = httpx.MockTransport(handler)
    sleep_calls: list[float] = []

    async def stub_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("elsevier_coordinate_extraction.client.asyncio.sleep", stub_sleep)

    async with ScienceDirectClient(_make_test_settings(max_wait=10.0), transport=transport) as client:
        result = await client.get_json("/quota")

    assert result["ok"] is True
    assert call_count == 2
    assert sleep_calls and sleep_calls[0] > 0


@pytest.mark.asyncio()
async def test_client_fails_when_wait_exceeds_threshold() -> None:
    """A wait duration longer than configured maximum should raise immediately."""

    async def handler(request: httpx.Request) -> httpx.Response:
        headers = {
            "Retry-After": "4000",
            "X-RateLimit-Reset": str(int(time.time()) + 4000),
        }
        return httpx.Response(429, headers=headers, json={"error": "limit"}, request=request)

    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(_make_test_settings(max_wait=60.0), transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError, match="exceeds configured maximum"):
            await client.get_json("/quota")
