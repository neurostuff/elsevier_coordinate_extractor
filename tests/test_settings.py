"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from elsevier_coordinate_extraction import settings


def test_get_settings_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Settings should respect environment variables and memoize the result."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.delenv("ELSEVIER_INSTTOKEN", raising=False)
    monkeypatch.delenv("ELSEVIER_HTTP_PROXY", raising=False)
    monkeypatch.delenv("ELSEVIER_HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ELSEVIER_USE_PROXY", raising=False)
    empty_env = tmp_path / "blank.env"
    empty_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(empty_env))
    cfg_a = settings.get_settings(force_reload=True)
    cfg_b = settings.get_settings()
    assert cfg_a.api_key == "unit-test-key"
    assert cfg_a.insttoken is None
    assert cfg_a.use_proxy is False
    assert cfg_a.extraction_workers == 0
    assert cfg_a.springer_api_key is None
    assert cfg_a.springer_base_url == "https://api.springernature.com"
    assert cfg_a.pubmed_base_url == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    assert cfg_a is cfg_b


def test_get_settings_requires_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Missing API key should raise a helpful error."""
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        settings.get_settings(force_reload=True)


def test_insttoken_optional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Optional institutional token should be loaded when provided."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.setenv("ELSEVIER_INSTTOKEN", "inst-token")
    monkeypatch.setenv("ELSEVIER_HTTP_PROXY", "http://proxy")
    monkeypatch.setenv("ELSEVIER_HTTPS_PROXY", "https://proxy")
    monkeypatch.delenv("ELSEVIER_USE_PROXY", raising=False)
    blank_env = tmp_path / "blank.env"
    blank_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(blank_env))
    cfg = settings.get_settings(force_reload=True)
    assert cfg.insttoken == "inst-token"
    assert cfg.http_proxy == "http://proxy"
    assert cfg.https_proxy == "https://proxy"
    assert cfg.use_proxy is True


def test_use_proxy_flag_disables_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dedicated flag should allow bypassing configured proxy endpoints."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.setenv("ELSEVIER_HTTP_PROXY", "socks5://localhost:1080")
    monkeypatch.setenv("ELSEVIER_USE_PROXY", "false")
    cfg = settings.get_settings(force_reload=True)
    assert cfg.http_proxy == "socks5://localhost:1080"
    assert cfg.use_proxy is False
    assert cfg.extraction_workers == 0


def test_max_rate_limit_wait_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The max wait threshold should be configurable via environment variable."""

    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    blank_env = tmp_path / "blank.env"
    blank_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(blank_env))
    monkeypatch.setenv("ELSEVIER_MAX_RATE_LIMIT_WAIT_SECONDS", "120")
    monkeypatch.setenv("ELSEVIER_EXTRACTION_WORKERS", "8")
    cfg = settings.get_settings(force_reload=True)
    assert cfg.max_rate_limit_wait == 120.0
    assert cfg.extraction_workers == 8


def test_max_rate_limit_wait_unlimited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Special values should allow disabling the wait threshold entirely."""

    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    blank_env = tmp_path / "blank.env"
    blank_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(blank_env))
    monkeypatch.setenv("ELSEVIER_MAX_RATE_LIMIT_WAIT_SECONDS", "none")
    cfg = settings.get_settings(force_reload=True)
    assert cfg.max_rate_limit_wait is None


def test_springer_and_pubmed_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Springer and PubMed integration settings should load from environment."""

    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.setenv("SPRINGER_API_KEY", "springer-key")
    monkeypatch.setenv("SPRINGER_BASE_URL", "https://springer.example")
    monkeypatch.setenv("PUBMED_BASE_URL", "https://ncbi.example/eutils")
    monkeypatch.setenv("NCBI_API_KEY", "ncbi-key")
    blank_env = tmp_path / "blank.env"
    blank_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(blank_env))
    cfg = settings.get_settings(force_reload=True)
    assert cfg.springer_api_key == "springer-key"
    assert cfg.springer_base_url == "https://springer.example"
    assert cfg.pubmed_base_url == "https://ncbi.example/eutils"
    assert cfg.ncbi_api_key == "ncbi-key"
