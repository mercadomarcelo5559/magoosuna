"""Estado temporal del flujo OAuth (protección CSRF + PKCE)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Platform


class OAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un `state` de OAuth pendiente de callback. De un solo uso."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    platform: Mapped[Platform] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    #: A dónde devolver el navegador al terminar (p. ej. la UI de Macaly).
    return_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: PKCE (TikTok desktop/mobile). Se almacena cifrado.
    code_verifier_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OAuthState {self.platform} {self.state[:8]}…>"
