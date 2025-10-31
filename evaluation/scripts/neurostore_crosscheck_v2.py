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
OUTPUT_PATH = Path('evaluation/data/elsevier_neurostore_crosscheck_v2.jsonl')
CACHE_NAMESPACE = 'science_direct_xml'

records = []
for line in INPUT_PATH.read_text().splitlines():
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


async def fetch_sciencedirect(id_dict: dict[str, str], client: ScienceDirectClient) -> dict[str, Any]:
    if not id_dict:
        return {'status': 'missing'}
    try:
        articles = await download_articles([id_dict], client=client, cache=cache, cache_namespace=CACHE_NAMESPACE)
    except httpx.HTTPStatusError as exc:
        return {'status': 'error', 'error': f'http_error:{exc.response.status_code}'}
    except Exception as exc:  # noqa: BLE001
        return {'status': 'error', 'error': str(exc)}
    if not articles:
        return {'status': 'error', 'error': 'empty_response'}
    art = articles[0]
    return {
        'status': 'ok',
        'doi': art.doi,
        'pii': art.metadata.get('pii'),
        'title': extract_title(art.payload),
        'identifier_type': art.metadata.get('identifier_type'),
        'identifier': art.metadata.get('identifier'),
        'view_obtained': art.metadata.get('view_obtained'),
    }


async def main() -> None:
    outputs: list[dict[str, Any]] = []
    async with ScienceDirectClient(settings) as client:
        for entry in records:
            doi = entry.get('doi')
            pmid = entry.get('pmid')
            neurostore_studies = entry.get('neurostore_studies') or []

            neurostore_dois = [study.get('source_id') for study in neurostore_studies if study.get('source_id')]
            neurostore_titles = [study.get('name') for study in neurostore_studies if study.get('name')]
            neuro_norm_dois = {normalize(ds) for ds in neurostore_dois if ds}
            neuro_norm_titles = {normalize(title) for title in neurostore_titles if title}

            # Prefer DOI; fallback to PMID if DOI missing.
            id_dict = {}
            if doi:
                id_dict['doi'] = doi
            elif pmid:
                id_dict['pmid'] = pmid

            sd_result = await fetch_sciencedirect(id_dict, client)

            sd_doi_norm = normalize(sd_result.get('doi')) if sd_result.get('doi') else ''
            sd_title_norm = normalize(sd_result.get('title')) if sd_result.get('title') else ''

            matches_neurostore = None
            if sd_result.get('status') == 'ok' and neurostore_studies:
                if sd_doi_norm and sd_doi_norm in neuro_norm_dois:
                    matches_neurostore = True
                elif neuro_norm_dois and sd_doi_norm:
                    matches_neurostore = False
                elif sd_title_norm and sd_title_norm in neuro_norm_titles:
                    matches_neurostore = True
                elif neuro_norm_titles and sd_title_norm:
                    matches_neurostore = False

            outputs.append(
                {
                    'doi': doi,
                    'pmid': pmid,
                    'science_direct_result': sd_result,
                    'neurostore_dois': neurostore_dois,
                    'neurostore_titles': neurostore_titles,
                    'matches_neurostore': matches_neurostore,
                }
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open('w', encoding='utf-8') as f:
        for row in outputs:
            json.dump(row, f)
            f.write('
')
    print('Wrote crosscheck v2 for', len(outputs), 'entries ->', OUTPUT_PATH)


if __name__ == '__main__':
    asyncio.run(main())
