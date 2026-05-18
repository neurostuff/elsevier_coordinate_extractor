"""PubMed identifier resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .settings import Settings

__all__ = ["PubMedResolver"]


def _http2_enabled() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


class PubMedResolver:
    """Resolve article identifiers from PubMed E-utilities."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, str | None] = {}

    async def __aenter__(self) -> PubMedResolver:
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def resolve_doi(self, pmid: str) -> str | None:
        """Resolve DOI for a PMID via NCBI ESummary."""
        normalized = pmid.strip()
        if not normalized:
            return None
        if normalized in self._cache:
            return self._cache[normalized]
        await self._ensure_client()
        assert self._client is not None
        params: dict[str, str] = {
            "db": "pubmed",
            "id": normalized,
            "retmode": "json",
        }
        if self._settings.ncbi_api_key:
            params["api_key"] = self._settings.ncbi_api_key
        response = await self._client.get("/esummary.fcgi", params=params)
        response.raise_for_status()
        payload = response.json()
        doi = _extract_doi_from_esummary(payload, normalized)
        self._cache[normalized] = doi
        return doi

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        timeout = httpx.Timeout(self._settings.timeout)
        headers = {"User-Agent": self._settings.user_agent}
        client_kwargs: dict[str, Any] = {
            "base_url": self._settings.pubmed_base_url,
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


def _extract_doi_from_esummary(
    payload: Mapping[str, Any],
    pmid: str,
) -> str | None:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return None

    record_obj = result.get(pmid)
    if not isinstance(record_obj, Mapping):
        for uid in _iter_uids(result):
            candidate = result.get(uid)
            if isinstance(candidate, Mapping):
                record_obj = candidate
                break
        if not isinstance(record_obj, Mapping):
            return None

    direct_doi = _normalize_doi(record_obj.get("doi"))
    if direct_doi:
        return direct_doi

    article_ids = record_obj.get("articleids")
    if not isinstance(article_ids, list):
        return None
    for article_id in article_ids:
        if not isinstance(article_id, Mapping):
            continue
        id_type = str(article_id.get("idtype", "")).strip().lower()
        value = article_id.get("value")
        normalized = _normalize_doi(value)
        if not normalized:
            continue
        if id_type in {"doi", "elocationid"}:
            return normalized
    return None


def _iter_uids(result: Mapping[str, Any]) -> list[str]:
    uids = result.get("uids")
    if not isinstance(uids, list):
        return []
    return [str(uid) for uid in uids if uid]


def _normalize_doi(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower.startswith("doi:"):
        text = text.split(":", 1)[1].strip()
    if not text.startswith("10."):
        return None
    return text
