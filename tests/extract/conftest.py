"""Shared fixtures for extraction integration tests."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from elsevier_coordinate_extraction import settings
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.types import ArticleContent


@pytest.fixture(scope="function", params=("doi", "pmid"), ids=("doi", "pmid"))
def downloaded_articles(
    request: pytest.FixtureRequest,
    test_dois: list[str],
    sample_test_pmids: list[str],
) -> list[ArticleContent]:
    """Download real articles for integration-style extraction tests."""

    identifier_type: str = request.param
    identifiers = test_dois if identifier_type == "doi" else sample_test_pmids

    async def _download() -> list[ArticleContent]:
        cfg = settings.get_settings()
        async with ScienceDirectClient(cfg) as client:
            try:
                records = [{identifier_type: value} for value in identifiers]
                article_list = await download_articles(records, client=client)
            except httpx.HTTPStatusError as exc:  # type: ignore[attr-defined]
                if exc.response.status_code in {401, 403}:
                    pytest.skip(
                        "ScienceDirect credentials unavailable for test run."
                    )
                raise
        return list(article_list)

    articles = asyncio.run(_download())
    if identifier_type == "pmid":
        for identifier, article in zip(identifiers, articles):
            assert article.metadata.get("identifier") == identifier
            assert article.metadata.get("identifier_type") == "pmid"

    class ArticleList(list[ArticleContent]):
        """Annotated list carrying identifier metadata."""

        pass

    wrapped = ArticleList(articles)
    setattr(wrapped, "identifier_type", identifier_type)
    setattr(wrapped, "identifiers", identifiers)
    return wrapped
