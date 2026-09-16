"""Selección del backend de almacenamiento según la configuración."""

from __future__ import annotations

import functools

from app.config import settings
from app.storage.base import StorageBackend, StoredObject
from app.storage.local import LocalStorage


@functools.lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    if settings.storage_backend == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage()
    return LocalStorage(settings.local_storage_path)


def reset_storage_cache() -> None:
    """Usado en tests al cambiar la configuración."""
    get_storage.cache_clear()


__all__ = ["LocalStorage", "StorageBackend", "StoredObject", "get_storage", "reset_storage_cache"]
