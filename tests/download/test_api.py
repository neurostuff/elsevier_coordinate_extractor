"""Download module tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from elsevier_coordinate_extraction import settings
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.settings import Settings
from elsevier_coordinate_extraction.types import ArticleContent


def _test_settings() -> Settings:
    """Return a Settings copy that disables proxies for mock transports."""

    cfg = settings.get_settings()
    return Settings(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
        concurrency=cfg.concurrency,
        cache_dir=cfg.cache_dir,
        user_agent=cfg.user_agent,
        insttoken=cfg.insttoken,
        http_proxy=None,
        https_proxy=None,
        use_proxy=False,
        max_rate_limit_wait=cfg.max_rate_limit_wait,
        extraction_workers=cfg.extraction_workers,
    )


@pytest.mark.asyncio()
@pytest.mark.vcr()
async def test_download_single_article_xml(test_dois: Sequence[str]) -> None:
    """Download an article by DOI and return the XML payload."""
    cfg = settings.get_settings()
    records = [{"doi": test_dois[0]}]
    async with ScienceDirectClient(cfg) as client:
        articles = await download_articles(records, client=client)
    assert len(articles) == 1
    article = articles[0]
    assert isinstance(article, ArticleContent)
    assert article.doi == test_dois[0]
    assert article.format == "xml"
    assert article.content_type.startswith("text/xml") or article.content_type == "application/xml"
    assert article.payload.lstrip().startswith(b"<")
    assert "pii" in article.metadata
    assert article.metadata["transport"] == "https"


@pytest.mark.asyncio()
async def test_download_marks_truncated_full_text() -> None:
    """When the payload lacks body content we should mark the view as STANDARD."""

    doi = "10.1016/j.neucli.2007.12.007"
    payload = b"""
    <article xmlns=\"http://www.elsevier.com/xml/svapi/article/dtd\" xmlns:ce=\"http://www.elsevier.com/xml/common/dtd\">
      <item-info>
        <pii>S0987-7053(08)00019-1</pii>
        <doi>10.1016/j.neucli.2007.12.007</doi>
      </item-info>
    </article>
    """.strip()

    captured_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert request.url.path == f"/content/article/doi/{doi}"
        assert request.headers.get("Accept") == "application/xml"
        assert request.url.params.get("view") == "FULL"
        return httpx.Response(200, content=payload, headers={"content-type": "application/xml"}, request=request)

    cfg = _test_settings()
    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(cfg, transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError, match="metadata-only payload"):
            await download_articles([{"doi": doi}], client=client)

    assert len(captured_requests) == 1


@pytest.mark.asyncio()
async def test_download_errors_when_full_view_invalid(test_dois: Sequence[str]) -> None:
    """Client should raise if Elsevier rejects FULL view requests."""

    doi = test_dois[0]

    async def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params.get("view") == "FULL"
        return httpx.Response(
            400,
            text="<service-error>View parameter specified in request is not valid</service-error>",
            headers={
                "content-type": "text/xml",
                "X-ELS-Status": "INVALID_INPUT - View parameter specified in request is not valid",
            },
            request=request,
        )

    cfg = _test_settings()
    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(cfg, transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError, match="rejected FULL view"):
            await download_articles([{"doi": doi}], client=client)


@pytest.mark.asyncio()
async def test_download_uses_cache(tmp_path: Path, test_dois: Sequence[str]) -> None:
    """When cached payload exists, avoid hitting HTTP transport."""

    class StubCache:
        def __init__(self) -> None:
            self.get_calls: list[str] = []
            self.set_calls: list[str] = []
            self.data: dict[str, bytes] = {}

        async def get(self, namespace: str, key: str) -> bytes | None:
            self.get_calls.append(key)
            return self.data.get(key)

        async def set(self, namespace: str, key: str, data: bytes) -> None:
            self.set_calls.append(key)
            self.data[key] = data

    stub_cache = StubCache()
    cached_payload = b"""
    <article xmlns=\"http://www.elsevier.com/xml/svapi/article/dtd\" xmlns:ce=\"http://www.elsevier.com/xml/common/dtd\">
      <ce:body><ce:para>cached</ce:para></ce:body>
    </article>
    """.strip()
    cached_key = f"doi:{test_dois[0]}"
    stub_cache.data[cached_key] = cached_payload

    cfg = settings.get_settings()

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP transport should not be called when cache hits.")

    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            [{"doi": test_dois[0]}],
            client=client,
            cache=stub_cache,
            cache_namespace="articles",
        )
    assert articles[0].payload == cached_payload
    assert cached_key in stub_cache.get_calls
    assert stub_cache.set_calls == []


@pytest.mark.asyncio()
async def test_download_article_by_pmid(sample_test_pmids: Sequence[str]) -> None:
    """Download an article by PubMed ID and ensure DOI metadata propagates."""
    pmid = sample_test_pmids[0]
    doi = "10.1016/j.stubbed.000001"
    payload = f"""
    <article xmlns=\"http://www.elsevier.com/xml/svapi/article/dtd\" xmlns:ce=\"http://www.elsevier.com/xml/common/dtd\">
      <item-info>
        <doi>{doi}</doi>
        <pii>S105381192400679X</pii>
      </item-info>
      <ce:body><ce:para>full text</ce:para></ce:body>
    </article>
    """.encode("utf-8")

    class StubClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, str] | None = None,
            accept: str | None = None,
        ) -> httpx.Response:
            self.calls.append((method, path))
            assert method == "GET"
            assert path == f"/article/pubmed_id/{pmid}"
            assert accept == "application/xml"
            assert params is not None
            assert params.get("httpAccept") == "text/xml"
            assert params.get("view") == "FULL"
            request = httpx.Request(
                method,
                f"https://api.elsevier.com/content{path}",
                params=params,
            )
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/xml",
                    "X-RateLimit-Limit": "100",
                    "X-RateLimit-Remaining": "99",
                    "X-RateLimit-Reset": "1234567891",
                },
                request=request,
            )

    client = StubClient()
    articles = await download_articles([{"pmid": pmid}], client=client)  # type: ignore[arg-type]

    assert len(articles) == 1
    article = articles[0]
    assert article.doi == doi
    assert article.metadata["identifier"] == pmid
    assert article.metadata["identifier_type"] == "pmid"
    assert article.metadata.get("doi") == doi
    assert article.metadata.get("pii") == "S105381192400679X"
    assert article.metadata.get("rate_limit_limit") == 100
    assert article.metadata.get("rate_limit_remaining") == 99
    assert article.metadata.get("rate_limit_reset_epoch") == 1234567891.0


@pytest.mark.asyncio()
async def test_download_progress_callback_invoked_for_each_record(test_dois: Sequence[str]) -> None:
    """Progress callback fires for every successfully downloaded record."""

    cfg = _test_settings()
    records = [{"doi": test_dois[0]}, {"doi": test_dois[1]}]

    async def handler(request: httpx.Request) -> httpx.Response:
        doi = request.url.path.rsplit("/", 1)[-1]
        payload = f"""
        <article xmlns="http://www.elsevier.com/xml/svapi/article/dtd" xmlns:ce="http://www.elsevier.com/xml/common/dtd">
          <item-info>
            <doi>{doi}</doi>
            <pii>S105381192400679X</pii>
          </item-info>
          <ce:body><ce:para>{doi}</ce:para></ce:body>
        </article>
        """.encode("utf-8")
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/xml"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(records, client=client, progress_callback=progress_cb)

    assert len(articles) == len(records)
    assert len(progress_calls) == len(records)
    assert [call[0]["doi"] for call in progress_calls] == [record["doi"] for record in records]
    assert all(call[1] is not None for call in progress_calls)
    assert all(call[2] is None for call in progress_calls)


@pytest.mark.asyncio()
async def test_download_progress_callback_receives_errors(test_dois: Sequence[str]) -> None:
    """Progress callback should receive exceptions before they propagate."""

    cfg = _test_settings()
    doi = test_dois[0]

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    transport = httpx.MockTransport(handler)
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    async def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        await asyncio.sleep(0)
        progress_calls.append((record, article, error))

    with pytest.raises(httpx.TimeoutException):
        async with ScienceDirectClient(cfg, transport=transport) as client:
            await download_articles([{"doi": doi}], client=client, progress_callback=progress_cb)

    assert len(progress_calls) == 1
    record, article, error = progress_calls[0]
    assert record["doi"] == doi
    assert article is None
    assert isinstance(error, httpx.TimeoutException)
