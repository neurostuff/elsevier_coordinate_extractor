# Elsvier Coordinate Extraction – Development Blueprint

## Package Layout & Interfaces

```
elsevier_coordinate_extraction/
├── __init__.py
├── settings.py
├── client.py
├── cache.py
├── rate_limits.py
├── nimads.py
├── types.py
├── search/
│   ├── __init__.py
│   └── api.py
├── download/
│   ├── __init__.py
│   └── api.py
├── extract/
│   ├── __init__.py
│   └── coordinates.py
└── pipeline.py
tests/
├── test_settings.py
├── search/
│   └── test_api.py
├── download/
│   └── test_api.py
├── extract/
│   └── test_coordinates.py
└── test_pipeline.py
```

### `settings.py`
- `@dataclass class Settings`: `api_key`, `base_url`, `timeout`, `concurrency`, `cache_dir`, `user_agent`.
- `get_settings() -> Settings`: loads `.env` via `python-dotenv`, memoizes the resulting object, validates required fields.

### `client.py`
- `class ScienceDirectClient`: async context manager wrapping `httpx.AsyncClient`.
  - Injects API key header (`X-Elsevier-APIKey`), default query params (e.g., `httpAccept`).
  - Accepts `Settings`, optional external `AsyncClient`.
  - Exposes `async get_json(path: str, params: dict[str, str]) -> dict`.
  - Exposes `async get_xml(path: str, params: dict[str, str]) -> str`.
  - Handles retry/backoff using response status and headers; `rate_limits.py` assists with parsing `Retry-After` and known ScienceDirect policy (fallback to static ceiling if headers absent).

**Client usage example**

```python
from elsevier_coordinate_extraction.client import ScienceDirectClient
from elsevier_coordinate_extraction.settings import get_settings

settings = get_settings()

async with ScienceDirectClient(settings) as client:
    result = await client.get_json(
        "/search/sciencedirect",
        params={"query": "TITLE(fmri)", "count": "1"},
    )
```

The client automatically applies API key and user agent headers, enforces the configured concurrency limit, and retries when the Elsevier API returns `Retry-After` metadata.

### `cache.py`
- `class FileCache`:
  - `async get(namespace: str, key: str) -> bytes | None`.
  - `async set(namespace: str, key: str, data: bytes, metadata: dict | None = None) -> None`.
  - Namespaces for `search`, `articles`, `assets`; keys derived from deterministic hashes.
- `CacheKey` helpers to hash query params and article identifiers.

### `types.py`
- `StudyMetadata`, `ArticleContent`, `AnalysisPayload`, `PointPayload` defined as `TypedDict`/`dataclass` to mirror NIMADS schema.
- `StudysetPayload` alias for the top-level structure handed between modules.

### `nimads.py`
- `def build_study(study_meta: StudyMetadata, *, analyses: list[AnalysisPayload] | None = None) -> dict`.
- `def build_studyset(name: str, studies: list[dict], metadata: dict | None = None) -> dict`.
- Optional `validate(payload: dict) -> None` hook using LinkML schemas if we decide to integrate them later (validation deferred for now).

### `search/api.py`
- `async def search_articles(query: str, *, max_results: int = 25, client: ScienceDirectClient | None = None, cache: FileCache | None = None) -> StudysetPayload`.
  - Builds ScienceDirect search endpoint params (`query`, `count`, `start`, requested fields for DOI/title/abstract/authors/openaccess flags).
  - Handles pagination until `max_results`.
  - Collects minimal study metadata (title, abstract, authors, journal, year, open access flag, DOI/PII/Scopus ID) in NIMADS `Study` format; attaches ScienceDirect identifiers to `metadata`.
  - Persists search responses via cache keyed by query hash.

### `download/api.py`
- `async def download_articles(studies: Sequence[StudyMetadata], *, formats: Sequence[str] = ("xml", "html"), client: ScienceDirectClient | None = None, cache: FileCache | None = None) -> list[ArticleContent]`.
  - Resolves best-available format per study (prioritize XML; fallback to HTML/PDF).
  - Uses `asyncio.Semaphore(settings.concurrency)` for parallel downloads.
  - Stores raw payload bytes and associated metadata (`content_type`, `is_open_access`, `retrieved_at`) in `ArticleContent`.
  - Persists downloads to cache using article-specific keys.

### `extract/coordinates.py`
- `def extract_coordinates(articles: Sequence[ArticleContent]) -> StudysetPayload`.
  - Parses XML with `lxml` (mirroring Pubget heuristics).
  - `def _iter_table_fragments(xml_root) -> Iterable[TableFragment]`: yields raw table XML and metadata.
  - `def _parse_table(table_fragment: str) -> list[PointPayload]`: ported logic from `pubget._coordinates`.
  - `def _infer_coordinate_space(article_element) -> str | None`: replicates Pubget coordinate space detection.
  - Returns NIMADS-ready structures: each study gets `analyses` populated with `points`, includes raw table XML snippets in `metadata`.

### `pipeline.py`
- `async def run_pipeline(query: str, *, max_results: int = 25, settings: Settings | None = None) -> StudysetPayload`.
  - Glues search → download → extract, reusing shared `ScienceDirectClient` and `FileCache`.
  - Returns final aggregated payload with both metadata and extracted coordinates.

## TDD Plan

1. **Settings & Configuration**
   - Write `test_settings.py` verifying `.env` loading, required key enforcement, and memoization.
   - Implement minimal `settings.py` until tests pass.

2. **HTTP Client Layer**
   - Draft `tests/search/test_client.py` (or inline in `test_api.py`) using `pytest-recording` to confirm headers, retries, and timeout behavior.
   - Implement `ScienceDirectClient` with httpx, stub out rate-limit parsing.

3. **Search Module**
   - Author tests that:
     - mock ScienceDirect responses (via recordings) to validate query building, pagination, metadata extraction, and cache hits.
     - assert returned structure matches NIMADS study schema fields (title, abstract, authors, year, journal, open-access flag).
   - Build `search/api.py` to satisfy tests.

4. **Download Module**
   - Create fixtures with recorded ScienceDirect full-text responses (XML + HTML fallback).
   - Tests cover: format preference, concurrency (mocked semaphore), cache usage, error handling/backoff.
   - Implement `download/api.py` accordingly.

5. **Extraction Module**
   - Begin with unit tests using sample XML snippets (derived from Pubget tests/examples) to ensure coordinate parsing matches expectations.
   - Add integration test comparing against a known article used in Pubget to validate coordinate and space inference.
   - Port necessary parsing helpers into `extract/coordinates.py`.

6. **Pipeline Integration**
   - Write async pipeline test with mocked modules to ensure data passed through correctly and NIMADS payload assembled.
   - Add optional recording-based end-to-end test gated behind marker to avoid frequent API calls.

7. **NIMADS Helpers & Validation**
   - Tests verifying builder functions assemble schemas correctly and that point metadata includes raw table XML fragments.
   - Implement `nimads.py` helpers plus optional schema validation toggle.

8. **Rate-Limit Handling**
   - Tests simulate responses with and without headers like `Retry-After` to check backoff logic.
   - Implement `rate_limits.py` to parse response headers and enforce delays (fall back to documented limits determined during implementation).

9. **Cache Layer**
   - Tests ensure deterministic key generation, read/write round-trips, and concurrent access safety.
   - Implement `FileCache` (async wrappers around `asyncio.to_thread` for disk IO if necessary).

10. **Documentation & Examples**
   - After functionality stabilizes, add README usage examples and docstrings, ensuring TDD artifacts remain green.

## Targeted Download & Extraction TDD (using test DOIs)

To exercise ScienceDirect endpoints without live dependencies, we use the `test_dois` fixture defined in `tests/conftest.py`. Recording rules:
- Set `PYTEST_RECORDING_MODE=once` (default). Update recordings intentionally when request parameters change.
- Recordings live under `tests/cassettes/download/` and `tests/cassettes/extract/`, named per test function.

### Download module tests
1. `tests/download/test_api.py::test_download_single_article_xml`
   - Uses cassette `download/test_download_single_article_xml.yaml`.
   - Asserts the API retrieves XML payload bytes, content type, and article identifiers (DOI, PII).
2. `test_download_handles_cached_payload`
   - Mocks cache layer; ensures cached entries skip HTTP call.
3. `test_download_parallel_respects_concurrency`
   - Parametrized with two DOIs; asserts semaphore limits concurrency via captured timestamps.

### Extraction module tests
1. `tests/extract/test_coordinates.py::test_extract_coordinates_from_sample_xml`
   - Loads recorded XML from download stage (fixture).
   - Validates we detect coordinate tables, parse xyz triplets, infer MNI/TAL space, and attach raw table XML.
2. `test_extract_returns_nimads_structure`
   - Confirms output includes `study`, `analyses`, and `points` fields shaped like NIMADS schema.
3. Integration test combining download + extract for a single DOI, using cached cassette to simulate full pipeline without external calls.

Each test should fail prior to implementation, guiding incremental development of `download/api.py`, extraction helpers, and new type utilities.

Throughout development, record HTTP interactions with `pytest-recording`, keep tests deterministic via cache fixtures, and use Ruff for linting.
