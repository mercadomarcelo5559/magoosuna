"""Cliente de la API (por ejemplo: la app de Macaly) y sus API keys."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.social_account import SocialAccount


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un tenant de la API. Cada API key pertenece a un cliente."""

    __tablename__ = "clients"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="client", cascade="all, delete-orphan", lazy="selectin"
    )
    social_accounts: Mapped[list[SocialAccount]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client {self.id} {self.name!r}>"


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """API key de un cliente. Solo se guarda el hash; el valor se muestra una vez."""

    __tablename__ = "api_keys"

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    #: SHA-256(pepper:key). Nunca la key en claro.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    #: Prefijo visible para identificarla en la UI/logs (no es secreto).
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(back_populates="api_keys", lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ApiKey {self.key_prefix}… client={self.client_id}>"
