"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from elsevier_coordinate_extraction import settings


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should respect environment variables and memoize the result."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.delenv("ELSEVIER_INSTTOKEN", raising=False)
    cfg_a = settings.get_settings(force_reload=True)
    cfg_b = settings.get_settings()
    assert cfg_a.api_key == "unit-test-key"
    assert cfg_a.insttoken is None
    assert cfg_a is cfg_b


def test_get_settings_requires_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Missing API key should raise a helpful error."""
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        settings.get_settings(force_reload=True)


def test_insttoken_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional institutional token should be loaded when provided."""
    monkeypatch.setenv("ELSEVIER_API_KEY", "unit-test-key")
    monkeypatch.setenv("ELSEVIER_INSTTOKEN", "inst-token")
    monkeypatch.setenv("ELSEVIER_HTTP_PROXY", "http://proxy")
    monkeypatch.setenv("ELSEVIER_HTTPS_PROXY", "https://proxy")
    cfg = settings.get_settings(force_reload=True)
    assert cfg.insttoken == "inst-token"
    assert cfg.http_proxy == "http://proxy"
    assert cfg.https_proxy == "https://proxy"
