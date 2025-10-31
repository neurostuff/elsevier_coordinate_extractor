import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from lxml import etree

from elsevier_coordinate_extraction.cache import FileCache
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.download.api import download_articles
from elsevier_coordinate_extraction.settings import get_settings

INPUT_PATH = Path('evaluation/data/elsevier_missing_coordinates_neurostore.jsonl')
OUTPUT_PATH = Path('evaluation/data/elsevier_neurostore_crosscheck_v4.jsonl')
CACHE_NAMESPACE = 'science_direct_xml'

records = []
with INPUT_PATH.open('r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

settings = get_settings()
cache = FileCache(settings.cache_dir / CACHE_NAMESPACE)


def normalize(text: str | None) -> str:
    if not text:
        return ''
    return re.sub(r'\W+', '', text.lower())


def extract_title(payload: bytes) -> str | None:
    try:
        root = etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return None
    ns = {k or 'ns': v for k, v in root.nsmap.items() if v}
    search_paths = [
        './/dc:title',
        './/ns:coredata/dc:title',
        './/ce:title',
        './/ns:full-text-retrieval-response//dc:title',
    ]
    for path in search_paths:
        try:
            result = root.xpath(path, namespaces=ns)
        except etree.XPathError:
            continue
        if result:
            val = result[0]
            if isinstance(val, etree._Element):
                val = ''.join(val.itertext())
            if isinstance(val, str):
                val = val.strip()
                if val:
                    return val
    return None


async def fetch_sciencedirect(identifier: dict[str, str], client: ScienceDirectClient) -> dict[str, Any]:
    if not identifier:
        return {'status': 'missing'}
    try:
        articles = await download_articles([identifier], client=client, cache=cache, cache_namespace=CACHE_NAMESPACE)
    except httpx.HTTPStatusError as exc:
        return {'status': 'error', 'error': f'http_error:{exc.response.status_code}'}
    except Exception as exc:
        return {'status': 'error', 'error': str(exc)}
    if not articles:
        return {'status': 'error', 'error': 'empty_response'}
    article = articles[0]
    return {
        'status': 'ok',
        'doi': article.doi,
        'pii': article.metadata.get('pii'),
        'title': extract_title(article.payload),
        'identifier_type': article.metadata.get('identifier_type'),
        'identifier': article.metadata.get('identifier'),
        'view_obtained': article.metadata.get('view_obtained'),
    }


async def main() -> None:
    outputs = []
    async with ScienceDirectClient(settings) as sd_client, httpx.AsyncClient(timeout=30.0, follow_redirects=True) as neuro_client:
        for entry in records:
            doi = entry.get('doi')
            pmid = entry.get('pmid')
            neurostore_entries = []
            neuro_doi_norms = set()
            neuro_title_norms = set()
            for study in entry.get('neurostore_studies') or []:
                study_id = study.get('study_id')
                if not study_id:
                    continue
                url = f'https://neurostore.org/api/studies/{study_id}'
                try:
                    resp = await neuro_client.get(url, params={'nested': 'true'})
                    resp.raise_for_status()
                    ns_data = resp.json()
                except httpx.HTTPError as exc:
                    neurostore_entries.append({'study_id': study_id, 'error': str(exc)})
                    continue
                if not isinstance(ns_data, dict):
                    neurostore_entries.append({'study_id': study_id, 'error': 'invalid_response'})
                    continue
                ns_doi = ns_data.get('doi') or (ns_data.get('metadata') or {}).get('doi') if isinstance(ns_data.get('metadata'), dict) else None
                ns_pmid = ns_data.get('pmid')
                neurostore_entries.append({'study_id': study_id, 'doi': ns_doi, 'pmid': ns_pmid})
                if ns_doi:
                    neuro_doi_norms.add(normalize(ns_doi))
                ns_title = ns_data.get('name')
                if ns_title:
                    neuro_title_norms.add(normalize(ns_title))

            identifier = {}
            if doi:
                identifier['doi'] = doi
            elif pmid:
                identifier['pmid'] = pmid
            sd_result = await fetch_sciencedirect(identifier, sd_client)

            match = None
            if sd_result.get('status') == 'ok' and (neuro_doi_norms or neuro_title_norms):
                sd_doi_norm = normalize(sd_result.get('doi'))
                sd_title_norm = normalize(sd_result.get('title'))
                if sd_doi_norm and sd_doi_norm in neuro_doi_norms:
                    match = True
                elif sd_doi_norm and neuro_doi_norms:
                    match = False
                elif sd_title_norm and sd_title_norm in neuro_title_norms:
                    match = True
                elif sd_title_norm and neuro_title_norms:
                    match = False

            outputs.append(
                {
                    'doi': doi,
                    'pmid': pmid,
                    'science_direct': sd_result,
                    'neurostore_studies': neurostore_entries,
                    'matches_neurostore': match,
                }
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open('w', encoding='utf-8') as f:
        for record in outputs:
            json.dump(record, f)
            f.write('
')
    print('Wrote crosscheck v4 for', len(outputs), 'entries ->', OUTPUT_PATH)


if __name__ == '__main__':
    asyncio.run(main())
