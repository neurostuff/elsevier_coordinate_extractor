"""Download module tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from elsevier_coordinate_extraction import settings
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.types import ArticleContent


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
@pytest.mark.vcr()
async def test_download_marks_truncated_full_text() -> None:
    """Some DOIs only return metadata even when FULL view is requested."""
    doi = "10.1016/j.neucli.2007.12.007"
    cfg = settings.get_settings()
    async with ScienceDirectClient(cfg) as client:
        articles = await download_articles([{"doi": doi}], client=client)

    assert len(articles) == 1
    article = articles[0]
    metadata = article.metadata

    assert metadata.get("view_requested") == "FULL"
    assert metadata.get("view_obtained") == "STANDARD"
    assert metadata.get("full_text_retrieved") is False
    # Ensure we still captured identifying information.
    assert metadata.get("pii") == "S0987-7053(08)00019-1"


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
    cached_payload = b"<xml>cached</xml>"
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
    <article>
      <item-info>
        <doi>{doi}</doi>
        <pii>S105381192400679X</pii>
      </item-info>
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
                headers={"content-type": "application/xml"},
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
