import json
from pathlib import Path

import pytest

from elsevier_coordinate_extraction.cli import orchestrator
from elsevier_coordinate_extraction.types import build_article_content
from elsevier_coordinate_extraction.settings import get_settings


@pytest.mark.asyncio
async def test_process_articles_creates_outputs(tmp_path: Path, monkeypatch):
    article = build_article_content(
        doi="10.1016/j.test",
        payload=b"<root/>",
        content_type="application/xml",
        fmt="xml",
        metadata={"identifier_lookup": {"doi": "10.1016/j.test"}},
    )

    async def fake_download(records, client, cache, progress_callback):
        await progress_callback(records[0], article, None)
        return [article]

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

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

    settings = get_settings()
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
