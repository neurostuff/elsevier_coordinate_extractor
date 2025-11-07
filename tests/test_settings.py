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
    empty_env = tmp_path / "blank.env"
    empty_env.write_text("")
    monkeypatch.setenv("ELSEVIER_DOTENV_PATH", str(empty_env))
    cfg_a = settings.get_settings(force_reload=True)
    cfg_b = settings.get_settings()
    assert cfg_a.api_key == "unit-test-key"
    assert cfg_a.insttoken is None
    assert cfg_a.use_proxy is False
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
