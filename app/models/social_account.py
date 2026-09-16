"""Cuenta social conectada (Instagram / TikTok / YouTube / …)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, as_utc, utcnow
from app.models.enums import Platform

if TYPE_CHECKING:
    from app.models.client import Client


class SocialAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Credenciales OAuth de una cuenta social. Los tokens están cifrados."""

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "platform", "external_account_id", name="uq_social_account_identity"
        ),
    )

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(String(32), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    #: Token cifrado con Fernet (prefijo `fernet:`). Ver app.security.crypto.
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expiration: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refresh_token_expiration: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    account_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    client: Mapped[Client] = relationship(back_populates="social_accounts")

    # ------------------------------------------------------------- helpers
    def token_expires_within(self, delta: timedelta) -> bool:
        """True si el access token caduca dentro de `delta` (o ya caducó)."""
        expiration = as_utc(self.token_expiration)
        if expiration is None:
            return False
        return expiration <= utcnow() + delta

    @property
    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token_encrypted)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SocialAccount {self.platform}:{self.account_name}>"
