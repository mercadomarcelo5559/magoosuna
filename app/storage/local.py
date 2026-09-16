"""Backend de almacenamiento en disco local (desarrollo / Codespaces)."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import IO

from app.storage.base import StorageBackend, StoredObject


class LocalStorage(StorageBackend):
    name = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """Resuelve `key` dentro de la raíz, impidiendo path traversal."""
        candidate = (self.root / key.lstrip("/")).resolve()
        if not str(candidate).startswith(str(self.root)):
            raise ValueError(f"Clave de almacenamiento inválida: {key!r}")
        return candidate

    def save(self, key: str, stream: IO[bytes], *, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
        return StoredObject(
            key=key, size_bytes=size, checksum_sha256=digest.hexdigest(), content_type=content_type
        )

    def open_stream(self, key: str, *, chunk_size: int) -> Iterator[bytes]:
        path = self._path(key)
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return
                yield chunk

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        # Limpia directorios vacíos hasta la raíz.
        parent = path.parent
        while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except ValueError:
            return False

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def local_path(self, key: str) -> str | None:
        return str(self._path(key))

    def free_space_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def total_bytes(self) -> int:
        total = 0
        for entry in self.root.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
        return total
