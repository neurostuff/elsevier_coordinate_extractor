"""Download module implementation."""

from __future__ import annotations

from contextlib import AsyncExitStack
import inspect
import re
from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Protocol

import httpx
from lxml import etree
from urllib.parse import urlparse

from elsevier_coordinate_extraction import rate_limits
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.pubmed import PubMedResolver
from elsevier_coordinate_extraction.springer_client import SpringerOpenAccessClient

from elsevier_coordinate_extraction.settings import Settings, get_settings
from elsevier_coordinate_extraction.types import ArticleContent, build_article_content

_PII_PATTERN = re.compile(rb"<pii[^>]*>([^<]+)</pii>", re.IGNORECASE)
_DOI_PATTERN = re.compile(
    rb"<(?P<tag>(?:\w+:)?doi)[^>]*>([^<]+)</(?P=tag)>",
    re.IGNORECASE,
)

_MIMETYPE_EXTENSION_MAP: dict[str, str] = {
    "application/word": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "text/csv": "csv",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
}

_CDN_BASE = "https://ars.els-cdn.com/content/image"


class ProgressCallback(
    Protocol,
):
    """Callback invoked after each record is processed."""

    def __call__(
        self,
        record: Mapping[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> Awaitable[None] | None: ...


class DownloadSkip(RuntimeError):
    """Raised when a record should be skipped with a specific reason."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.skip_reason = reason
        super().__init__(message or reason)


async def download_articles(
    records: Sequence[Mapping[str, str]],
    *,
    client: ScienceDirectClient | None = None,
    springer_client: SpringerOpenAccessClient | None = None,
    pubmed_resolver: PubMedResolver | None = None,
    cache: Any | None = None,
    cache_namespace: str = "articles",
    settings: Settings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[ArticleContent]:
    """Download ScienceDirect articles identified by DOI and/or PubMed ID records.

    Each record in ``records`` should contain at least one of the keys ``"doi"`` or ``"pmid"``.
    For every record, the downloader first attempts to retrieve the FULL text using the DOI
    (when present); if that fails, it retries with the PubMed ID. A successful download using
    either identifier stops further attempts for that record.

    When ``progress_callback`` is provided it will be invoked after each record finishes processing.
    The callback receives the original record, the downloaded ``ArticleContent`` when successful
    (``None`` when no payload is returned), and the exception raised while processing
    (``None`` on success). Callbacks may be synchronous or async functions. Download processing
    continues through the full list even when individual records fail.
    """
    if not records:
        return []

    cfg = settings or get_settings()
    springer_blocked_reason: str | None = None
    owns_client = client is None
    sci_client = client or ScienceDirectClient(cfg)
    owns_springer_client = springer_client is None
    springer_oa_client = springer_client or SpringerOpenAccessClient(cfg)
    owns_pubmed_resolver = pubmed_resolver is None
    pmid_resolver = pubmed_resolver or PubMedResolver(cfg)

    async def _emit_progress(
        record: Mapping[str, str],
        article: ArticleContent | None,
        error: BaseException | None,
    ) -> None:
        if progress_callback is None:
            return
        result = progress_callback(record, article, error)
        if inspect.isawaitable(result):
            await result

    async def _runner() -> list[ArticleContent]:
        nonlocal springer_blocked_reason
        results: list[ArticleContent] = []
        for record in records:
            article: ArticleContent | None = None
            try:
                article = await _download_record(
                    record=record,
                    settings=cfg,
                    elsevier_client=sci_client,
                    springer_client=springer_oa_client,
                    pubmed_resolver=pmid_resolver,
                    cache=cache,
                    cache_namespace=cache_namespace,
                    springer_blocked_reason=springer_blocked_reason,
                )
            except Exception as exc:
                if getattr(exc, "skip_reason", None) == "springer_rate_limited":
                    springer_blocked_reason = str(exc)
                await _emit_progress(record, None, exc)
                continue
            if article is None:
                await _emit_progress(record, None, None)
                continue
            results.append(article)
            await _emit_progress(record, article, None)
        return results

    async with AsyncExitStack() as stack:
        if owns_client:
            await stack.enter_async_context(sci_client)
        if owns_springer_client:
            await stack.enter_async_context(springer_oa_client)
        if owns_pubmed_resolver:
            await stack.enter_async_context(pmid_resolver)
        return await _runner()


async def _download_record(
    record: Mapping[str, str],
    *,
    settings: Settings,
    elsevier_client: ScienceDirectClient,
    springer_client: SpringerOpenAccessClient,
    pubmed_resolver: PubMedResolver,
    cache: Any | None,
    cache_namespace: str,
    springer_blocked_reason: str | None,
) -> ArticleContent | None:
    doi = (record.get("doi") or "").strip()
    pmid = (record.get("pmid") or "").strip()

    article = await _download_elsevier_record(
        record=record,
        client=elsevier_client,
        cache=cache,
        cache_namespace=cache_namespace,
    )
    if article is not None:
        return article

    if not settings.springer_api_key:
        raise DownloadSkip("springer_unconfigured")
    if springer_blocked_reason:
        raise DownloadSkip("springer_rate_limited", springer_blocked_reason)

    resolved_doi = doi
    if not resolved_doi:
        if not pmid:
            raise DownloadSkip("pmid_to_doi_unresolved")
        try:
            resolved = await pubmed_resolver.resolve_doi(pmid)
        except Exception as exc:  # pragma: no cover - network/transport dependent
            raise DownloadSkip("pmid_to_doi_unresolved") from exc
        if not resolved:
            raise DownloadSkip("pmid_to_doi_unresolved")
        resolved_doi = resolved

    springer_record = await _fetch_springer_metadata_record(
        doi=resolved_doi,
        client=springer_client,
    )
    if springer_record is None:
        raise DownloadSkip("springer_not_found")

    try:
        springer_article = await _download_springer_jats(
            doi=resolved_doi,
            record=springer_record,
            client=springer_client,
            cache=cache,
            cache_namespace=cache_namespace,
        )
    except httpx.HTTPStatusError as exc:
        if _is_rate_limited_error(exc):
            raise DownloadSkip("springer_rate_limited", str(exc)) from exc
        raise
    if springer_article is None:
        raise DownloadSkip("springer_jats_unavailable")

    springer_article.metadata.setdefault("identifier_lookup", dict(record))
    return springer_article


async def _download_elsevier_record(
    *,
    record: Mapping[str, str],
    client: ScienceDirectClient,
    cache: Any | None,
    cache_namespace: str,
) -> ArticleContent | None:
    doi = (record.get("doi") or "").strip()
    pmid = (record.get("pmid") or "").strip()

    attempts: list[tuple[str, str]] = []
    if doi:
        attempts.append(("doi", doi))
    if pmid and pmid not in {value for _, value in attempts}:
        attempts.append(("pmid", pmid))

    if not attempts:
        raise ValueError("Each record must provide at least a 'doi' or 'pmid'.")

    last_error: httpx.HTTPStatusError | None = None
    for identifier_type, identifier in attempts:
        try:
            article = await _download_identifier(
                identifier=identifier,
                identifier_type=identifier_type,
                client=client,
                cache=cache,
                cache_namespace=cache_namespace,
            )
        except httpx.HTTPStatusError as exc:
            last_error = exc
            continue

        article.metadata.setdefault("identifier_lookup", dict(record))
        return article

    if last_error is not None and last_error.response.status_code == 404:
        return None
    if last_error is not None:
        raise last_error
    return None


async def _fetch_springer_metadata_record(
    *,
    doi: str,
    client: SpringerOpenAccessClient,
) -> dict[str, Any] | None:
    query = _build_springer_doi_query(doi)
    try:
        data = await client.get_json(
            "/openaccess/json",
            params={
                "q": query,
                "s": "1",
                "p": "1",
            },
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        if _is_rate_limited_error(exc):
            raise DownloadSkip("springer_rate_limited", str(exc)) from exc
        raise
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return None
    first = records[0]
    if not isinstance(first, Mapping):
        return None
    return dict(first)


async def _download_springer_jats(
    *,
    doi: str,
    record: Mapping[str, Any],
    client: SpringerOpenAccessClient,
    cache: Any | None,
    cache_namespace: str,
) -> ArticleContent | None:
    query = _build_springer_doi_query(doi)
    cache_key = f"springer-jats:doi:{doi}"
    payload: bytes | None = None
    content_type = "application/xml"
    metadata: dict[str, Any] = {
        "provider": "springer",
        "source_api": "openaccess",
        "resolved_doi": doi,
        "springer_record": _summarize_springer_record(record),
    }

    if cache is not None:
        cached = await cache.get(cache_namespace, cache_key)
        if cached is not None:
            payload = cached
            metadata["transport"] = "cache"

    if payload is None:
        try:
            response = await client.request(
                "GET",
                "/openaccess/jats",
                params={
                    "q": query,
                    "s": "1",
                    "p": "1",
                },
                accept="application/xml",
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        payload = response.content
        content_type = response.headers.get("content-type", "application/xml")
        metadata.update(
            {
                "transport": response.request.url.scheme,
                "status_code": response.status_code,
            }
        )
        snapshot = rate_limits.get_rate_limit_snapshot(response)
        metadata.update(snapshot.to_metadata())
        if cache is not None:
            await cache.set(cache_namespace, cache_key, payload)

    if not _payload_contains_springer_full_text(payload):
        return None

    extracted_doi = _extract_doi(payload)
    metadata["full_text_retrieved"] = True
    metadata["doi"] = extracted_doi or doi
    return build_article_content(
        doi=extracted_doi or doi,
        payload=payload,
        content_type=content_type,
        format="xml",
        metadata=metadata,
    )


async def _download_identifier(
    *,
    identifier: str,
    identifier_type: str,
    client: ScienceDirectClient,
    cache: Any | None,
    cache_namespace: str,
) -> ArticleContent:
    identifier_type = identifier_type.lower()
    if identifier_type not in {"doi", "pmid"}:
        raise ValueError("identifier_type must be either 'doi' or 'pmid'")

    cache_key = _cache_key_for_identifier(identifier, identifier_type)
    payload: bytes | None = None
    metadata: dict[str, Any] = {}
    content_type = "application/xml"
    initial_view = "FULL"

    if cache is not None:
        cached = await cache.get(cache_namespace, cache_key)
        if cached is not None:
            payload = cached
            metadata["transport"] = "cache"

    view_used = initial_view
    response_for_metadata: httpx.Response | None = None
    if payload is None:
        path = _endpoint_path_for_identifier(identifier, identifier_type)
        params = {"httpAccept": "text/xml", "view": view_used}
        try:
            response = await client.request(
                "GET",
                path,
                params=params,
                accept="application/xml",
            )
        except httpx.HTTPStatusError as exc:
            if (
                view_used == "FULL"
                and exc.response.status_code == 400
                and _is_invalid_view_error(exc.response)
            ):
                message = (
                    "ScienceDirect rejected FULL view for "
                    f"{identifier_type}:{identifier}. Ensure your credentials grant full-text access."
                )
                raise httpx.HTTPStatusError(
                    message,
                    request=exc.request,
                    response=exc.response,
                ) from exc
            raise
        payload = response.content
        content_type = response.headers.get("content-type", "application/xml")
        response_for_metadata = response
        metadata.update(
            {
                "transport": response.request.url.scheme,
                "status_code": response.status_code,
                "view": view_used,
                "view_requested": initial_view,
                "view_obtained": view_used,
                "identifier": identifier,
                "identifier_type": identifier_type,
            }
        )
        snapshot = rate_limits.get_rate_limit_snapshot(response)
        metadata.update(snapshot.to_metadata())
        if cache is not None:
            await cache.set(cache_namespace, cache_key, payload)

    full_text = _payload_contains_full_text(payload)
    inferred_view = "FULL" if full_text else "STANDARD"
    if initial_view == "FULL" and not full_text:
        message = (
            "ScienceDirect returned metadata-only payload when FULL view was requested. "
            "Confirm your entitlements allow full-text retrieval."
        )
        if response_for_metadata is not None:
            raise httpx.HTTPStatusError(
                message,
                request=response_for_metadata.request,
                response=response_for_metadata,
            )
        raise RuntimeError(message + " Cached payload violates requirement.")

    metadata["view_requested"] = metadata.get("view_requested", initial_view)
    metadata["view_obtained"] = inferred_view
    metadata["view"] = inferred_view
    metadata["full_text_retrieved"] = full_text
    metadata.setdefault("provider", "elsevier")

    pii = _extract_pii(payload)
    metadata.setdefault("pii", pii)

    extracted_doi = _extract_doi(payload)
    if extracted_doi:
        metadata.setdefault("doi", extracted_doi)

    supplementary = _extract_supplementary_links(payload)
    if supplementary:
        metadata["supplementary_attachments"] = supplementary

    if identifier_type == "doi":
        article_doi = identifier
    else:
        article_doi = extracted_doi or identifier
    metadata.setdefault("resolved_doi", article_doi)

    return build_article_content(
        doi=article_doi,
        payload=payload,
        content_type=content_type,
        format="xml",
        metadata=metadata,
    )


def _extract_pii(payload: bytes) -> str | None:
    match = _PII_PATTERN.search(payload)
    if match is None:
        return None
    try:
        return match.group(1).decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def _extract_doi(payload: bytes) -> str | None:
    match = _DOI_PATTERN.search(payload)
    if match is None:
        return None
    try:
        return match.group(2).decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def _cache_key_for_identifier(identifier: str, identifier_type: str) -> str:
    return f"{identifier_type}:{identifier}"


def _endpoint_path_for_identifier(identifier: str, identifier_type: str) -> str:
    if identifier_type == "doi":
        return f"/article/doi/{identifier}"
    if identifier_type == "pmid":
        return f"/article/pubmed_id/{identifier}"
    raise ValueError(f"Unsupported identifier type: {identifier_type}")


def _payload_contains_full_text(payload: bytes) -> bool:
    try:
        root = etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return False
    ns = {"ce": "http://www.elsevier.com/xml/common/dtd"}
    if root.xpath(".//ce:body", namespaces=ns):
        return True
    if root.xpath(".//ce:section", namespaces=ns):
        return True
    if root.xpath(".//ce:para", namespaces=ns) or root.xpath(".//ce:simple-para", namespaces=ns):
        return True
    if root.xpath('.//*[local-name()="table"]'):
        return True
    return False


def _extract_supplementary_links(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return []

    ns_raw = root.nsmap
    ns = {prefix or "ns": uri for prefix, uri in ns_raw.items() if uri}
    attachments: list[dict[str, Any]] = []
    if ns:
        objects = root.xpath(".//ns:object", namespaces=ns)
    else:
        objects = root.findall(".//object")
    for obj in objects:
        ref = (obj.get("ref") or "").strip()
        obj_type = (obj.get("type") or "").strip().lower()
        category = (obj.get("category") or "").strip().lower()
        if not ref:
            continue
        if not (
            ref.lower().startswith("mm")
            or "supp" in ref.lower()
            or "supp" in obj_type
            or obj_type == "application"
            or "application" in category
        ):
            continue
        raw_url = (obj.text or "").strip()
        if not raw_url:
            raw_url = obj.get("{http://www.w3.org/1999/xlink}href", "").strip()
        if not raw_url:
            continue

        mimetype = (obj.get("mimetype") or "").strip().lower()
        multimediatype = obj.get("multimediatype")
        size = obj.get("size")
        inferred_ext = _infer_extension(raw_url, mimetype)
        cdn_url = _guess_cdn_url(raw_url, inferred_ext)

        attachments.append(
            {
                "ref": ref,
                "type": obj.get("type"),
                "category": obj.get("category"),
                "mimetype": mimetype,
                "multimediatype": multimediatype,
                "size": size,
                "api_url": raw_url,
                "cdn_url": cdn_url,
                "extension": inferred_ext,
            }
        )
    return attachments


def _infer_extension(url: str, mimetype: str) -> str | None:
    extension = _MIMETYPE_EXTENSION_MAP.get(mimetype.lower())
    parsed = urlparse(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    if "." in filename:
        current_ext = filename.rsplit(".", 1)[-1]
        if not extension:
            return current_ext.lower()
        # Special case: upgrade legacy doc to docx
        if extension == "docx" and current_ext.lower() == "doc":
            return "docx"
        return extension
    return extension


def _guess_cdn_url(api_url: str, extension: str | None) -> str | None:
    parsed = urlparse(api_url)
    path = parsed.path
    if "/eid/" not in path:
        return None
    filename = path.split("/eid/", 1)[1]
    if extension:
        if "." in filename:
            base, _ = filename.rsplit(".", 1)
            filename = f"{base}.{extension}"
        else:
            filename = f"{filename}.{extension}"
    return f"{_CDN_BASE}/{filename}"


def _summarize_springer_record(record: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "identifier",
        "doi",
        "title",
        "publicationName",
        "journalTitle",
        "publicationDate",
    )
    summary: dict[str, Any] = {}
    for field in fields:
        value = record.get(field)
        if value:
            summary[field] = value
    return summary


def _build_springer_doi_query(doi: str) -> str:
    """Build a Springer query value that treats DOI characters literally."""
    escaped = doi.strip().replace("\\", "\\\\").replace('"', '\\"')
    return f'doi:"{escaped}"'


def _payload_contains_springer_full_text(payload: bytes) -> bool:
    try:
        root = etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return False
    body_present = root.xpath(
        './/*[local-name()="body" or local-name()="sec" or local-name()="p"]'
    )
    if body_present:
        return True
    table_present = root.xpath(
        './/*[local-name()="table-wrap" or local-name()="table"]'
    )
    return bool(table_present)


def _is_invalid_view_error(response: httpx.Response) -> bool:
    """Detect Elsevier errors indicating the requested view is unsupported."""

    status_header = response.headers.get("X-ELS-Status", "").lower()
    if "view" in status_header and "invalid" in status_header:
        return True
    try:
        body_text = response.text.lower()
    except Exception:  # pragma: no cover - defensive fallback
        return False
    return "view" in body_text and "not valid" in body_text


def _is_rate_limited_error(exc: httpx.HTTPStatusError) -> bool:
    """Return True when the failure is an HTTP 429/rate-limit response."""
    response = exc.response
    return response is not None and response.status_code == 429
