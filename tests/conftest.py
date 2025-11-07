"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = ("pytest_asyncio",)


def _strip_cookies(response: dict[str, Any]) -> dict[str, Any]:
    """Remove volatile cookie headers before storing responses."""
    response.get("headers", {}).pop("Set-Cookie", None)
    response.get("headers", {}).pop("set-cookie", None)
    return response


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, Any]:
    """Configure pytest-recording for cassette storage and header scrubbing."""
    cassette_dir = Path(__file__).parent / "cassettes"
    cassette_dir.mkdir(parents=True, exist_ok=True)
    return {
        "cassette_library_dir": str(cassette_dir),
        "record_mode": os.getenv("PYTEST_RECORDING_MODE", "once"),
        "filter_headers": [
            "authorization",
            "x-api-key",
            "x-els-apikey",
            "cookie",
            "set-cookie",
            "user-agent",
        ],
        "filter_query_parameters": [
            "apiKey",
            "apikey",
            "api_key",
            "access_token",
        ],
        "decode_compressed_response": True,
        "allow_playback_repeats": True,
        "before_record_response": _strip_cookies,
    }


@pytest.fixture
def vcr_cassette(vcr: Any, request: pytest.FixtureRequest):
    """Automatically open a cassette per-test (module/testname)."""

    module = request.node.module.__name__.replace(".", "_")
    path = Path("auto") / module / f"{request.node.name}.yaml"
    with vcr.use_cassette(str(path)):
        yield


@pytest.fixture(scope="session")
def test_dois() -> list[str]:
    """Provide a set of DOIs for use in tests."""
    return [
        "10.1016/j.nbd.2012.03.039",
        "10.1016/j.nbd.2008.08.001",
        "10.1016/j.ntt.2005.12.008",
        "10.1016/j.neuro.2015.07.002",
    ]

@pytest.fixture(scope="session")
def sample_test_pmids() -> list[str]:
    """Provide a set of sample test PMIDs for use in tests."""
    return [
        "31262544",
        "19159636",
        "19540923",
        "10660227",
    ]
