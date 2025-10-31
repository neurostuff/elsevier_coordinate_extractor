"""Application configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

_DEFAULT_BASE_URL: Final[str] = "https://api.elsevier.com/content"
_DEFAULT_TIMEOUT: Final[float] = 30.0
_DEFAULT_CONCURRENCY: Final[int] = 4
_DEFAULT_CACHE_DIR: Final[str] = ".elsevier_cache"
_DEFAULT_USER_AGENT: Final[str] = "elsevierCoordinateExtraction/0.1.0"

_CACHED_SETTINGS: Settings | None = None


@dataclass(frozen=True)
class Settings:
    """Runtime configuration derived from environment variables."""

    api_key: str
    base_url: str
    timeout: float
    concurrency: int
    cache_dir: Path
    user_agent: str
    insttoken: str | None
    http_proxy: str | None
    https_proxy: str | None


def get_settings(*, force_reload: bool = False) -> Settings:
    """Load configuration, optionally reloading from the environment."""
    global _CACHED_SETTINGS  # noqa: PLW0603
    if not force_reload and _CACHED_SETTINGS is not None:
        return _CACHED_SETTINGS

    dotenv_override = os.getenv("ELSEVIER_DOTENV_PATH")
    if dotenv_override:
        load_dotenv(dotenv_override, override=True)
    else:
        dotenv_path = Path.cwd() / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path=dotenv_path)

    api_key = os.getenv("ELSEVIER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELSEVIER_API_KEY must be set in the environment or .env file."
        )

    base_url = os.getenv("ELSEVIER_BASE_URL", _DEFAULT_BASE_URL)
    timeout = float(os.getenv("ELSEVIER_TIMEOUT", _DEFAULT_TIMEOUT))
    concurrency = int(os.getenv("ELSEVIER_CONCURRENCY", _DEFAULT_CONCURRENCY))
    cache_dir_raw = os.getenv("ELSEVIER_CACHE_DIR", _DEFAULT_CACHE_DIR)
    cache_dir = Path(cache_dir_raw).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    user_agent = os.getenv("ELSEVIER_USER_AGENT", _DEFAULT_USER_AGENT)
    insttoken = os.getenv("ELSEVIER_INSTTOKEN")
    http_proxy = os.getenv("ELSEVIER_HTTP_PROXY")
    https_proxy = os.getenv("ELSEVIER_HTTPS_PROXY")

    _CACHED_SETTINGS = Settings(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        concurrency=concurrency,
        cache_dir=cache_dir,
        user_agent=user_agent,
        insttoken=insttoken,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
    )
    return _CACHED_SETTINGS
