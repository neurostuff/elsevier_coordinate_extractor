"""Tests for PubMed DOI resolution."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from elsevier_coordinate_extraction.pubmed import PubMedResolver
from elsevier_coordinate_extraction.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_key="test-elsevier",
        base_url="https://api.elsevier.com/content",
        timeout=30.0,
        concurrency=2,
        cache_dir=Path("."),
        user_agent="test-agent",
        insttoken=None,
        http_proxy=None,
        https_proxy=None,
        use_proxy=False,
        max_rate_limit_wait=60.0,
        extraction_workers=0,
        springer_api_key=None,
        springer_base_url="https://api.springernature.com",
        pubmed_base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ncbi_api_key="ncbi-key",
    )


@pytest.mark.asyncio()
async def test_pubmed_resolver_extracts_doi() -> None:
    pmid = "31262544"
    expected_doi = "10.1000/example-doi"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/esummary.fcgi")
        assert request.url.params.get("db") == "pubmed"
        assert request.url.params.get("id") == pmid
        assert request.url.params.get("retmode") == "json"
        assert request.url.params.get("api_key") == "ncbi-key"
        payload = {
            "header": {"type": "esummary"},
            "result": {
                "uids": [pmid],
                pmid: {
                    "uid": pmid,
                    "articleids": [
                        {"idtype": "pubmed", "value": pmid},
                        {"idtype": "doi", "value": expected_doi},
                    ],
                },
            },
        }
        return httpx.Response(200, json=payload, request=request)

    transport = httpx.MockTransport(handler)
    async with PubMedResolver(_settings(), transport=transport) as resolver:
        doi = await resolver.resolve_doi(pmid)
    assert doi == expected_doi


@pytest.mark.asyncio()
async def test_pubmed_resolver_returns_none_when_missing_doi() -> None:
    pmid = "99999999"

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "result": {
                "uids": [pmid],
                pmid: {
                    "uid": pmid,
                    "articleids": [{"idtype": "pubmed", "value": pmid}],
                },
            },
        }
        return httpx.Response(200, json=payload, request=request)

    transport = httpx.MockTransport(handler)
    async with PubMedResolver(_settings(), transport=transport) as resolver:
        doi = await resolver.resolve_doi(pmid)
    assert doi is None


@pytest.mark.asyncio()
async def test_pubmed_resolver_raises_for_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server"}, request=request)

    transport = httpx.MockTransport(handler)
    async with PubMedResolver(_settings(), transport=transport) as resolver:
        with pytest.raises(httpx.HTTPStatusError):
            await resolver.resolve_doi("12345")
