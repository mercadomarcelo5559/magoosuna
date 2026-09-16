"""Contrato común de todos los providers de red social.

Añadir una plataforma nueva (Facebook, X, LinkedIn…) consiste en:
 1. Implementar `BaseProvider` en `app/providers/<plataforma>/provider.py`.
 2. Registrarla en `app/providers/registry.py`.
 3. Añadir sus credenciales a `config.py` y a `.env.example`.
Nada más del sistema necesita cambiar.
"""

from __future__ import annotations

import abc
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from app.models.enums import Platform


@dataclass(slots=True)
class OAuthCredentials:
    """Resultado de un intercambio/refresh de tokens."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AccountInfo:
    """Identidad de la cuenta conectada."""

    external_account_id: str
    account_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthorizationRequest:
    """URL a la que debe navegar el usuario final + datos a guardar."""

    url: str
    state: str
    code_verifier: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoSource:
    """De dónde sale el video para esta publicación.

    - `public_url`: URL HTTPS accesible por la plataforma (Instagram la exige;
      TikTok la admite con dominio verificado).
    - `open_stream`: callable que devuelve un iterador de bytes (upload directo).
    """

    filename: str
    content_type: str
    size_bytes: int
    public_url: str | None = None
    open_stream: Callable[[], Iterator[bytes]] | None = None
    local_path: str | None = None

    @property
    def has_stream(self) -> bool:
        return self.open_stream is not None or self.local_path is not None


@dataclass(slots=True)
class PublishRequest:
    """Todo lo que un provider necesita para publicar un video."""

    video: VideoSource
    caption: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    #: Estado persistido de intentos previos (container_id, publish_id…).
    state: dict[str, Any] = field(default_factory=dict)
    #: Callback para persistir progreso entre pasos (sobrevive a reintentos).
    on_state: Callable[[dict[str, Any]], None] | None = None
    #: Callback de cambio de fase (uploading/processing/publishing).
    on_stage: Callable[[str], None] | None = None

    def save_state(self, **values: Any) -> None:
        self.state.update(values)
        if self.on_state:
            self.on_state(dict(self.state))

    def set_stage(self, stage: str) -> None:
        if self.on_stage:
            self.on_stage(stage)


@dataclass(slots=True)
class PublishResult:
    """Identificadores devueltos por la plataforma tras publicar."""

    external_post_id: str
    external_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RemoteStatus:
    """Estado del contenido en la plataforma."""

    state: str
    is_final: bool
    external_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BaseProvider(abc.ABC):
    """Interfaz que implementa cada plataforma."""

    platform: ClassVar[Platform]
    #: Texto mostrado en `GET /v1/platforms` cuando falta configuración.
    setup_docs_url: ClassVar[str] = ""

    # --------------------------------------------------------------- OAuth
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True si hay client id/secret y redirect URI en el entorno."""

    @abc.abstractmethod
    def build_authorization_request(self, *, state: str, redirect_uri: str) -> AuthorizationRequest:
        """Construye la URL del diálogo de autorización (paso 1 de `connect`)."""

    @abc.abstractmethod
    def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> OAuthCredentials:
        """Canjea el `code` del callback por tokens (paso 2 de `connect`)."""

    @abc.abstractmethod
    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Renueva el access token. Lanza `AuthenticationError` si no es posible."""

    @abc.abstractmethod
    def get_account(self, credentials: OAuthCredentials) -> AccountInfo:
        """Obtiene id y nombre de la cuenta autorizada."""

    # ---------------------------------------------------------- publicación
    @abc.abstractmethod
    def publish(self, credentials: OAuthCredentials, request: PublishRequest) -> PublishResult:
        """Sube y publica el video. Debe ser reanudable usando `request.state`."""

    @abc.abstractmethod
    def get_post_status(self, credentials: OAuthCredentials, external_post_id: str) -> RemoteStatus:
        """Consulta el estado del contenido ya enviado a la plataforma."""

    # -------------------------------------------------------------- extras
    def revoke(self, credentials: OAuthCredentials) -> None:  # noqa: ARG002 - parte del contrato
        """Revoca el token en la plataforma. Por defecto no-op."""
        return None

    def requires_public_url(self) -> bool:
        """True si la plataforma sólo acepta `video_url` públicas."""
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.platform}>"
