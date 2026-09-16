"""Activo de video almacenado temporalmente."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MediaSource, MediaStatus


class MediaAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Video subido por el cliente o referenciado por URL pública.

    Los ficheros viven en el backend de almacenamiento (local o S3/R2) y se
    borran cuando ya no son necesarios (ver `app.services.retention`).
    """

    __tablename__ = "media_assets"

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[MediaSource] = mapped_column(String(16), nullable=False)
    status: Mapped[MediaStatus] = mapped_column(
        String(16), default=MediaStatus.PENDING, nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Backend y clave del objeto ("local"/"s3"). Vacío si `source == URL`.
    storage_backend: Mapped[str | None] = mapped_column(String(16), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: URL pública original cuando el cliente aportó una URL en lugar de fichero.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asset_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    @property
    def is_external_url(self) -> bool:
        return self.source == MediaSource.URL and bool(self.source_url)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MediaAsset {self.id} {self.filename!r} {self.status}>"
