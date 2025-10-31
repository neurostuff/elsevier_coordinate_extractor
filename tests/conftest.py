"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, Any]:
    """Configure pytest-recording for cassette storage and header scrubbing."""
    cassette_dir = Path(__file__).parent / "cassettes"
    cassette_dir.mkdir(parents=True, exist_ok=True)
    return {
        "cassette_library_dir": str(cassette_dir),
        "record_mode": os.getenv("PYTEST_RECORDING_MODE", "once"),
        "filter_headers": ["X-Elsevier-Apikey", "Authorization"],
        "filter_query_parameters": [("apiKey", "DUMMY")],
    }


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
