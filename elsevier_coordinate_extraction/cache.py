"""Disk-backed cache helpers."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path


class FileCache:
    """Simple asynchronous cache that stores payloads on disk."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    async def get(self, namespace: str, key: str) -> bytes | None:
        """Return cached bytes if present."""
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def set(self, namespace: str, key: str, data: bytes) -> None:
        """Persist payload bytes for future reuse."""
        path = self._path(namespace, key)
        await asyncio.to_thread(self._write_atomic, path, data)

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        directory = self._root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{digest}.bin"

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(path)
