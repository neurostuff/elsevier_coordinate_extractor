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
    """Return deterministic Settings for mock transport tests."""

    return Settings(
        api_key="test-api-key",
        base_url="https://api.elsevier.com/content",
        timeout=30.0,
        concurrency=4,
        cache_dir=Path(".elsevier_cache").resolve(),
        user_agent="elsevierCoordinateExtraction/tests",
        insttoken=None,
        http_proxy=None,
        https_proxy=None,
        use_proxy=False,
        max_rate_limit_wait=3600.0,
        extraction_workers=0,
        springer_api_key=None,
        springer_base_url="https://api.springernature.com",
        pubmed_base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ncbi_api_key=None,
    )


def _test_settings_with_springer() -> Settings:
    cfg = _test_settings()
    return Settings(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
        concurrency=cfg.concurrency,
        cache_dir=cfg.cache_dir,
        user_agent=cfg.user_agent,
        insttoken=cfg.insttoken,
        http_proxy=cfg.http_proxy,
        https_proxy=cfg.https_proxy,
        use_proxy=cfg.use_proxy,
        max_rate_limit_wait=cfg.max_rate_limit_wait,
        extraction_workers=cfg.extraction_workers,
        springer_api_key="springer-key",
        springer_base_url=cfg.springer_base_url,
        pubmed_base_url=cfg.pubmed_base_url,
        ncbi_api_key=cfg.ncbi_api_key,
    )


def _test_settings_without_springer() -> Settings:
    cfg = _test_settings()
    return Settings(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
        concurrency=cfg.concurrency,
        cache_dir=cfg.cache_dir,
        user_agent=cfg.user_agent,
        insttoken=cfg.insttoken,
        http_proxy=cfg.http_proxy,
        https_proxy=cfg.https_proxy,
        use_proxy=cfg.use_proxy,
        max_rate_limit_wait=cfg.max_rate_limit_wait,
        extraction_workers=cfg.extraction_workers,
        springer_api_key=None,
        springer_base_url=cfg.springer_base_url,
        pubmed_base_url=cfg.pubmed_base_url,
        ncbi_api_key=cfg.ncbi_api_key,
    )


@pytest.mark.asyncio()
@pytest.mark.vcr()
async def test_download_single_article_xml(test_dois: Sequence[str]) -> None:
    """Download an article by DOI and return the XML payload."""
    try:
        cfg = settings.get_settings()
    except RuntimeError as exc:
        if "ELSEVIER_API_KEY" in str(exc):
            pytest.skip("ELSEVIER_API_KEY unavailable for live download test.")
        raise
    records = [{"doi": test_dois[0]}]
    async with ScienceDirectClient(cfg) as client:
        articles = await download_articles(records, client=client, settings=cfg)
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
    """When the payload lacks body content we emit an error but keep going."""

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
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            [{"doi": doi}],
            client=client,
            settings=cfg,
            progress_callback=progress_cb,
        )

    assert len(captured_requests) == 1
    assert articles == []
    assert len(progress_calls) == 1
    record, article, error = progress_calls[0]
    assert record["doi"] == doi
    assert article is None
    assert isinstance(error, httpx.HTTPStatusError)


@pytest.mark.asyncio()
async def test_download_errors_when_full_view_invalid(test_dois: Sequence[str]) -> None:
    """Client reports invalid FULL view errors without raising."""

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
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            [{"doi": doi}],
            client=client,
            settings=cfg,
            progress_callback=progress_cb,
        )

    assert articles == []
    assert len(progress_calls) == 1
    record, article, error = progress_calls[0]
    assert record["doi"] == doi
    assert article is None
    assert isinstance(error, httpx.HTTPStatusError)


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

    cfg = _test_settings()

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP transport should not be called when cache hits.")

    transport = httpx.MockTransport(handler)
    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            [{"doi": test_dois[0]}],
            client=client,
            settings=cfg,
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
    articles = await download_articles(
        [{"pmid": pmid}],
        client=client,  # type: ignore[arg-type]
        settings=_test_settings(),
    )

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
        articles = await download_articles(
            records,
            client=client,
            settings=cfg,
            progress_callback=progress_cb,
        )

    assert len(articles) == len(records)
    assert len(progress_calls) == len(records)
    assert [call[0]["doi"] for call in progress_calls] == [record["doi"] for record in records]
    assert all(call[1] is not None for call in progress_calls)
    assert all(call[2] is None for call in progress_calls)


@pytest.mark.asyncio()
async def test_download_progress_callback_receives_errors(test_dois: Sequence[str]) -> None:
    """Progress callback should receive exceptions even when downloads do not raise."""

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

    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            [{"doi": doi}],
            client=client,
            settings=cfg,
            progress_callback=progress_cb,
        )

    assert articles == []
    assert len(progress_calls) == 1
    record, article, error = progress_calls[0]
    assert record["doi"] == doi
    assert article is None
    assert isinstance(error, httpx.TimeoutException)


@pytest.mark.asyncio()
async def test_download_continues_after_identifier_error(test_dois: Sequence[str]) -> None:
    """Errors for one record should not prevent later records from being processed."""

    cfg = _test_settings()
    bad_doi, good_doi = test_dois[:2]

    call_counter = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_counter
        call_counter += 1
        doi = request.url.path.rsplit("/", 1)[-1]
        if call_counter == 1:
            raise httpx.TimeoutException("simulated timeout")
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

    records = [{"doi": bad_doi}, {"doi": good_doi}]
    async with ScienceDirectClient(cfg, transport=transport) as client:
        articles = await download_articles(
            records,
            client=client,
            settings=cfg,
            progress_callback=progress_cb,
        )

    assert len(articles) == 1
    assert articles[0].doi == good_doi
    assert len(progress_calls) == 2
    assert progress_calls[0][0]["doi"] == bad_doi
    assert progress_calls[0][1] is None
    assert isinstance(progress_calls[0][2], httpx.TimeoutException)
    assert progress_calls[1][0]["doi"] == good_doi
    assert progress_calls[1][1] is not None
    assert progress_calls[1][2] is None


@pytest.mark.asyncio()
async def test_download_falls_back_to_springer_after_elsevier_not_found() -> None:
    doi = "10.1007/s00123-001-0001-1"
    call_order: list[str] = []

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            call_order.append("elsevier")
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class StubSpringerClient:
        async def get_json(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
        ) -> dict[str, object]:
            call_order.append("springer-metadata")
            assert path == "/openaccess/json"
            assert params == {"q": f"doi:{doi}", "s": "1", "p": "1"}
            return {"records": [{"doi": doi, "title": "Springer Test"}]}

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, str] | None = None,
            accept: str | None = None,
        ) -> httpx.Response:
            call_order.append("springer-jats")
            assert method == "GET"
            assert path == "/openaccess/jats"
            assert params == {"q": f"doi:{doi}", "s": "1", "p": "1"}
            assert accept == "application/xml"
            payload = b"""
            <article xmlns=\"http://jats.nlm.nih.gov\">
              <front><article-meta><article-id pub-id-type=\"doi\">10.1007/s00123-001-0001-1</article-id></article-meta></front>
              <body><sec><p>Springer full text</p></sec></body>
            </article>
            """.strip()
            request = httpx.Request(method, "https://api.springernature.com/openaccess/jats")
            return httpx.Response(
                200,
                request=request,
                content=payload,
                headers={"content-type": "application/xml"},
            )

    class StubPubMedResolver:
        async def resolve_doi(self, pmid: str) -> str | None:
            raise AssertionError("PMID resolver should not be called for DOI input.")

    articles = await download_articles(
        [{"doi": doi}],
        client=StubElsevierClient(),  # type: ignore[arg-type]
        springer_client=StubSpringerClient(),  # type: ignore[arg-type]
        pubmed_resolver=StubPubMedResolver(),  # type: ignore[arg-type]
        settings=_test_settings_with_springer(),
    )

    assert len(articles) == 1
    article = articles[0]
    assert article.doi == doi
    assert article.metadata["provider"] == "springer"
    assert article.metadata["resolved_doi"] == doi
    assert call_order == ["elsevier", "springer-metadata", "springer-jats"]


@pytest.mark.asyncio()
async def test_download_resolves_pmid_to_doi_for_springer_fallback() -> None:
    pmid = "31262544"
    resolved_doi = "10.1007/s00429-024-10000-1"

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class StubSpringerClient:
        async def get_json(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
        ) -> dict[str, object]:
            assert path == "/openaccess/json"
            assert params == {"q": f"doi:{resolved_doi}", "s": "1", "p": "1"}
            return {"records": [{"doi": resolved_doi, "title": "Resolved DOI"}]}

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, str] | None = None,
            accept: str | None = None,
        ) -> httpx.Response:
            payload = f"""
            <article xmlns="http://jats.nlm.nih.gov">
              <front><article-meta><article-id pub-id-type="doi">{resolved_doi}</article-id></article-meta></front>
              <body><sec><p>Body text</p></sec></body>
            </article>
            """.encode("utf-8")
            request = httpx.Request(method, "https://api.springernature.com/openaccess/jats")
            return httpx.Response(
                200,
                request=request,
                content=payload,
                headers={"content-type": "application/xml"},
            )

    class StubPubMedResolver:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def resolve_doi(self, value: str) -> str | None:
            self.calls.append(value)
            return resolved_doi

    resolver = StubPubMedResolver()
    articles = await download_articles(
        [{"pmid": pmid}],
        client=StubElsevierClient(),  # type: ignore[arg-type]
        springer_client=StubSpringerClient(),  # type: ignore[arg-type]
        pubmed_resolver=resolver,  # type: ignore[arg-type]
        settings=_test_settings_with_springer(),
    )

    assert len(articles) == 1
    assert resolver.calls == [pmid]
    assert articles[0].metadata["provider"] == "springer"
    assert articles[0].metadata["resolved_doi"] == resolved_doi


@pytest.mark.asyncio()
async def test_download_reports_skip_reason_when_springer_jats_missing() -> None:
    doi = "10.1007/s12345-6789-0"
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class StubSpringerClient:
        async def get_json(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
        ) -> dict[str, object]:
            return {"records": [{"doi": doi, "title": "Metadata only"}]}

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, str] | None = None,
            accept: str | None = None,
        ) -> httpx.Response:
            payload = b"<records><result><recordsDisplayed>0</recordsDisplayed></result></records>"
            request = httpx.Request(method, "https://api.springernature.com/openaccess/jats")
            return httpx.Response(
                200,
                request=request,
                content=payload,
                headers={"content-type": "application/xml"},
            )

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    articles = await download_articles(
        [{"doi": doi}],
        client=StubElsevierClient(),  # type: ignore[arg-type]
        springer_client=StubSpringerClient(),  # type: ignore[arg-type]
        settings=_test_settings_with_springer(),
        progress_callback=progress_cb,
    )
    assert articles == []
    assert len(progress_calls) == 1
    _, article, error = progress_calls[0]
    assert article is None
    assert error is not None
    assert getattr(error, "skip_reason", None) == "springer_jats_unavailable"


@pytest.mark.asyncio()
async def test_download_reports_skip_reason_when_springer_unconfigured() -> None:
    doi = "10.1007/s12345-6789-1"
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    articles = await download_articles(
        [{"doi": doi}],
        client=StubElsevierClient(),  # type: ignore[arg-type]
        settings=_test_settings_without_springer(),
        progress_callback=progress_cb,
    )
    assert articles == []
    assert len(progress_calls) == 1
    _, article, error = progress_calls[0]
    assert article is None
    assert error is not None
    assert getattr(error, "skip_reason", None) == "springer_unconfigured"


@pytest.mark.asyncio()
async def test_download_reports_skip_reason_when_springer_rate_limited() -> None:
    doi = "10.1007/s12345-6789-2"
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class StubSpringerClient:
        async def get_json(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
        ) -> dict[str, object]:
            request = httpx.Request("GET", "https://api.springernature.com/openaccess/json")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError(
                "Rate limit reset wait exceeds configured maximum (3600s).",
                request=request,
                response=response,
            )

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    articles = await download_articles(
        [{"doi": doi}],
        client=StubElsevierClient(),  # type: ignore[arg-type]
        springer_client=StubSpringerClient(),  # type: ignore[arg-type]
        settings=_test_settings_with_springer(),
        progress_callback=progress_cb,
    )
    assert articles == []
    assert len(progress_calls) == 1
    _, article, error = progress_calls[0]
    assert article is None
    assert error is not None
    assert getattr(error, "skip_reason", None) == "springer_rate_limited"


@pytest.mark.asyncio()
async def test_download_short_circuits_springer_after_rate_limit() -> None:
    records = [{"doi": "10.1007/s12345-6789-3"}, {"doi": "10.1007/s12345-6789-4"}]
    progress_calls: list[tuple[dict[str, str], ArticleContent | None, BaseException | None]] = []

    class StubElsevierClient:
        async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
            request = httpx.Request(method, f"https://api.elsevier.com/content{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class StubSpringerClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get_json(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
        ) -> dict[str, object]:
            self.calls += 1
            request = httpx.Request("GET", "https://api.springernature.com/openaccess/json")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError(
                "Springer OpenAccess rate limit wait (7200s) exceeds configured maximum (3600s).",
                request=request,
                response=response,
            )

    def progress_cb(
        record: dict[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        progress_calls.append((record, article, error))

    springer = StubSpringerClient()
    articles = await download_articles(
        records,
        client=StubElsevierClient(),  # type: ignore[arg-type]
        springer_client=springer,  # type: ignore[arg-type]
        settings=_test_settings_with_springer(),
        progress_callback=progress_cb,
    )

    assert articles == []
    assert springer.calls == 1
    assert len(progress_calls) == 2
    for _, article, error in progress_calls:
        assert article is None
        assert error is not None
        assert getattr(error, "skip_reason", None) == "springer_rate_limited"
