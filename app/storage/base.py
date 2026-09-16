"""Contrato de almacenamiento de objetos.

Diseñado para cambiar de `local` (desarrollo en Codespaces) a S3 / Cloudflare R2
(producción) sin tocar la lógica de negocio: sólo `STORAGE_BACKEND` en el .env.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO


@dataclass(slots=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str


class StorageBackend(abc.ABC):
    name: str

    @abc.abstractmethod
    def save(self, key: str, stream: IO[bytes], *, content_type: str) -> StoredObject:
        """Guarda el contenido del stream bajo `key`."""

    @abc.abstractmethod
    def open_stream(self, key: str, *, chunk_size: int) -> Iterator[bytes]:
        """Itera el contenido del objeto en bloques."""

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Borra el objeto (idempotente)."""

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """True si el objeto existe."""

    @abc.abstractmethod
    def size(self, key: str) -> int:
        """Tamaño del objeto en bytes."""

    def local_path(self, key: str) -> str | None:  # noqa: ARG002 - firma del contrato
        """Ruta en disco si el backend es local; `None` en remotos."""
        return None

    def public_url(self, key: str) -> str | None:  # noqa: ARG002 - firma del contrato
        """URL pública permanente si el backend la ofrece; `None` si no."""
        return None
