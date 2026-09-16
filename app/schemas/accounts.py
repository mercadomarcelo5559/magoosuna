"""Schemas de cuentas sociales y OAuth."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.enums import Platform


class SocialAccountResponse(BaseModel):
    """Cuenta conectada. Nunca incluye tokens."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: Platform
    account_name: str
    external_account_id: str
    scopes: list[str] = Field(default_factory=list)
    is_active: bool
    token_expiration: datetime | None = None
    has_refresh_token: bool = False
    last_refreshed_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_account(cls, account: Any) -> SocialAccountResponse:
        """Construye la respuesta filtrando los campos sensibles del metadata."""
        raw = dict(account.account_metadata or {})
        # Los tokens de Página de Facebook viven en metadata: no se exponen.
        safe = {
            key: value
            for key, value in raw.items()
            if "token" not in key.lower() and "secret" not in key.lower()
        }
        return cls(
            id=account.id,
            platform=account.platform,
            account_name=account.account_name,
            external_account_id=account.external_account_id,
            scopes=list(account.scopes or []),
            is_active=account.is_active,
            token_expiration=account.token_expiration,
            has_refresh_token=bool(account.refresh_token_encrypted),
            last_refreshed_at=account.last_refreshed_at,
            last_error=account.last_error,
            created_at=account.created_at,
            updated_at=account.updated_at,
            metadata=safe,
        )


class AuthorizeResponse(BaseModel):
    """URL a la que Macaly debe redirigir al usuario final."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "platform": "instagram",
                "authorization_url": "https://www.instagram.com/oauth/authorize?...",
                "state": "3f1c…",
                "expires_in": 600,
            }
        }
    )

    platform: Platform
    authorization_url: str
    state: str
    expires_in: int = Field(description="Segundos de validez del `state`")


class OAuthCallbackResponse(BaseModel):
    platform: Platform
    account: SocialAccountResponse
    message: str


class RefreshResponse(BaseModel):
    account: SocialAccountResponse
    refreshed: bool
    message: str


class CreatorInfoResponse(BaseModel):
    """Datos del creador de TikTok (privacidad permitida, límites)."""

    platform: Platform = Platform.TIKTOK
    data: dict[str, Any]


class PublishingLimitResponse(BaseModel):
    """Cuota de publicación de Instagram en las últimas 24 h."""

    platform: Platform = Platform.INSTAGRAM
    quota_usage: int | None = None
    config: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ConnectManualRequest(BaseModel):
    """Conexión con un token ya obtenido fuera de la API (uso avanzado).

    Útil para pruebas o para tokens de larga duración generados en el portal
    de cada plataforma. El token se cifra igual que en el flujo OAuth.
    """

    platform: Platform
    access_token: str = Field(min_length=10, description="Access token de la plataforma")
    refresh_token: str | None = None
    expires_in_seconds: int | None = Field(
        default=None, ge=60, description="Vida del access token en segundos"
    )
    scopes: list[str] = Field(default_factory=list)
    external_account_id: str | None = Field(
        default=None,
        description="Se autodetecta si se omite (llamando a la API de la plataforma)",
    )
    account_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthorizeQuery(BaseModel):
    return_url: HttpUrl | None = Field(
        default=None,
        description="A dónde devolver el navegador al terminar el OAuth (UI de Macaly)",
    )
