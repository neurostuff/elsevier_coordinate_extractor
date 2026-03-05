import json
from pathlib import Path

import pytest

from elsevier_coordinate_extraction.cli import orchestrator
from elsevier_coordinate_extraction.settings import Settings
from elsevier_coordinate_extraction.types import build_article_content


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def build_settings(cache_dir: Path) -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://api.elsevier.com/content",
        timeout=30.0,
        concurrency=1,
        cache_dir=cache_dir,
        user_agent="test-agent",
        insttoken=None,
        http_proxy=None,
        https_proxy=None,
        use_proxy=False,
        max_rate_limit_wait=60.0,
        extraction_workers=0,
    )


@pytest.mark.asyncio
async def test_process_articles_creates_outputs(tmp_path: Path, monkeypatch):
    article = build_article_content(
        doi="10.1016/j.test",
        payload=b"<root/>",
        content_type="application/xml",
        format="xml",
        metadata={"identifier_lookup": {"doi": "10.1016/j.test"}},
    )

    async def fake_download(records, client, cache, progress_callback):
        await progress_callback(records[0], article, None)
        return [article]

    monkeypatch.setattr(orchestrator, "download_articles", fake_download)
    monkeypatch.setattr(
        orchestrator,
        "ScienceDirectClient",
        lambda settings: DummyClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_text_from_article",
        lambda payload: {"title": "stub"},
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_tables_from_article",
        lambda payload: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_coordinates",
        lambda articles: {"studyset": {"studies": []}},
    )

    settings = build_settings(tmp_path / ".cache")
    stats = await orchestrator.process_articles(
        [{"doi": "10.1016/j.test"}],
        tmp_path,
        settings=settings,
        use_cache=False,
        verbose=True,
    )

    assert stats["success"] == 1
    article_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert article_dirs, "Expected at least one article directory"
    article_dir = article_dirs[0]
    assert (article_dir / "article.xml").exists()

    manifest = tmp_path / "manifest.jsonl"
    assert manifest.exists()
    data = json.loads(manifest.read_text().strip())
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_process_articles_updates_download_progress(tmp_path: Path, monkeypatch):
    article = build_article_content(
        doi="10.1016/j.test",
        payload=b"<root/>",
        content_type="application/xml",
        format="xml",
        metadata={"identifier_lookup": {"doi": "10.1016/j.test"}},
    )
    records = [{"doi": "10.1016/j.test"}, {"pmid": "12345678"}]

    async def fake_download(records, client, cache, progress_callback):
        await progress_callback(records[0], article, None)
        await progress_callback(records[1], None, None)
        return [article]

    class FakeTqdm:
        def __init__(self, iterable=None, total=None, **kwargs):
            self.iterable = iterable
            self.total = total
            self.updates: list[int] = []

        def update(self, value=1):
            self.updates.append(value)

        def write(self, message):
            return None

        def close(self):
            return None

        def __iter__(self):
            if self.iterable is None:
                return iter(())
            return iter(self.iterable)

    bars = []

    def fake_tqdm(*args, **kwargs):
        iterable = args[0] if args else kwargs.pop("iterable", None)
        bar = FakeTqdm(iterable=iterable, **kwargs)
        bars.append(bar)
        return bar

    monkeypatch.setattr(orchestrator, "download_articles", fake_download)
    monkeypatch.setattr(orchestrator, "tqdm", fake_tqdm)
    monkeypatch.setattr(
        orchestrator,
        "ScienceDirectClient",
        lambda settings: DummyClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_text_from_article",
        lambda payload: {"title": "stub"},
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_tables_from_article",
        lambda payload: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_coordinates",
        lambda articles: {"studyset": {"studies": []}},
    )

    settings = build_settings(tmp_path / ".cache")
    await orchestrator.process_articles(
        records,
        tmp_path,
        settings=settings,
        use_cache=False,
    )

    assert len(bars) == 2
    assert sum(bars[0].updates) == len(records)


@pytest.mark.asyncio
async def test_process_articles_continues_on_error_by_default(tmp_path: Path, monkeypatch):
    first_article = build_article_content(
        doi="10.1016/j.one",
        payload=b"<root/>",
        content_type="application/xml",
        format="xml",
        metadata={"identifier_lookup": {"doi": "10.1016/j.one"}},
    )
    second_article = build_article_content(
        doi="10.1016/j.two",
        payload=b"<root/>",
        content_type="application/xml",
        format="xml",
        metadata={"identifier_lookup": {"doi": "10.1016/j.two"}},
    )
    records = [{"doi": "10.1016/j.one"}, {"doi": "10.1016/j.two"}]

    async def fake_download(records, client, cache, progress_callback):
        await progress_callback(records[0], first_article, None)
        await progress_callback(records[1], second_article, None)
        return [first_article, second_article]

    calls = {"count": 0}

    def fake_extract_text(article):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("failed to parse article")
        return {"title": "stub"}

    monkeypatch.setattr(orchestrator, "download_articles", fake_download)
    monkeypatch.setattr(
        orchestrator,
        "ScienceDirectClient",
        lambda settings: DummyClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_text_from_article",
        fake_extract_text,
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_tables_from_article",
        lambda payload: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_coordinates",
        lambda articles: {"studyset": {"studies": []}},
    )

    settings = build_settings(tmp_path / ".cache")
    stats = await orchestrator.process_articles(
        records,
        tmp_path,
        settings=settings,
        use_cache=False,
    )

    assert stats["success"] == 1
    assert stats["failed"] == 1
    assert stats["skipped"] == 0

    manifest = tmp_path / "manifest.jsonl"
    statuses = [
        json.loads(line)["status"]
        for line in manifest.read_text().splitlines()
    ]
    assert statuses.count("success") == 1
    assert statuses.count("failed") == 1
