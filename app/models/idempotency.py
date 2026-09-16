"""Claves de idempotencia: evitan publicar dos veces la misma solicitud."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IdempotencyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Respuesta cacheada para un `Idempotency-Key` de un cliente."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("client_id", "key", name="uq_idempotency_client_key"),)

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    #: SHA-256 del cuerpo normalizado: si cambia, se responde 409.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IdempotencyRecord {self.client_id}:{self.key}>"
