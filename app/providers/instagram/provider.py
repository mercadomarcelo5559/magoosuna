"""InstagramProvider — Instagram Content Publishing API oficial de Meta.

Documentación de referencia (consultada para esta implementación):
  * https://developers.facebook.com/docs/instagram-platform/content-publishing
  * https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login

Requisitos de la plataforma (validados/documentados, no inventados):
  * La cuenta de Instagram debe ser **Professional** (Business o Creator).
    Las cuentas personales NO pueden publicar por API.
  * Permisos necesarios:
      - Business Login for Instagram (graph.instagram.com):
        `instagram_business_basic`, `instagram_business_content_publish`
      - Facebook Login for Business (graph.facebook.com):
        `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`
        (+ `pages_show_list` para localizar la Página vinculada)
  * Límite de publicación: 100 posts publicados por API en 24 h por cuenta.
    Consultable en `GET /<IG_ID>/content_publishing_limit`.

Flujo de publicación de un Reel/video (3 pasos + upload opcional):
  1. `POST /<IG_ID>/media` → crea el contenedor.
       - con `video_url` público, o
       - con `upload_type=resumable` y subida binaria a rupload.facebook.com
  2. `GET /<CONTAINER_ID>?fields=status_code` → esperar `FINISHED`
     (Meta recomienda consultar 1 vez por minuto, máximo ~5 minutos).
  3. `POST /<IG_ID>/media_publish` con `creation_id=<CONTAINER_ID>`.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.models.base import utcnow
from app.models.enums import Platform
from app.providers.base import (
    AccountInfo,
    AuthorizationRequest,
    BaseProvider,
    OAuthCredentials,
    PublishRequest,
    PublishResult,
    RemoteStatus,
)
from app.providers.errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidVideoError,
    PermanentProviderError,
    ProcessingTimeoutError,
    ProviderError,
    RateLimitError,
    TransientProviderError,
)
from app.utils.http import build_client, json_body, parse_retry_after, request
from app.utils.polling import poll_ticks

logger = get_logger(__name__)

#: Códigos de error de Meta que indican problemas con el propio video.
_MEDIA_ERROR_SUBCODES = {2207026, 2207020, 2207032, 2207003, 2207005, 2207023}
#: Códigos que indican token inválido o permisos insuficientes.
_AUTH_ERROR_CODES = {102, 190, 200, 2500, 10, 3}
#: Códigos de rate limit de la Graph API.
_RATE_LIMIT_CODES = {4, 17, 32, 613, 80004}


class InstagramProvider(BaseProvider):
    platform: ClassVar[Platform] = Platform.INSTAGRAM
    setup_docs_url: ClassVar[str] = (
        "https://developers.facebook.com/docs/instagram-platform/content-publishing"
    )

    # ------------------------------------------------------------ config
    @property
    def uses_instagram_login(self) -> bool:
        return settings.instagram_login_mode == "instagram"

    @property
    def graph_base(self) -> str:
        base = (
            settings.instagram_graph_base
            if self.uses_instagram_login
            else settings.instagram_facebook_graph_base
        )
        return f"{base.rstrip('/')}/{settings.instagram_graph_version}"

    @property
    def rupload_base(self) -> str:
        return f"{settings.instagram_rupload_base.rstrip('/')}/{settings.instagram_graph_version}"

    def is_configured(self) -> bool:
        return bool(settings.instagram_app_id and settings.instagram_app_secret)

    def requires_public_url(self) -> bool:
        # Instagram acepta ambas vías; usamos `video_url` si la tenemos y si no
        # el upload resumable. Por eso no forzamos URL pública.
        return False

    def _require_config(self) -> None:
        if not self.is_configured():
            raise ConfigurationError(
                "Instagram no está configurado: define INSTAGRAM_APP_ID e "
                "INSTAGRAM_APP_SECRET en el .env "
                "(App de Meta → https://developers.facebook.com/apps)"
            )

    # ------------------------------------------------------- errores Meta
    @staticmethod
    def _parse_error(response: httpx.Response) -> ProviderError | None:
        payload = json_body(response)
        error = payload.get("error")
        if not isinstance(error, dict):
            return None

        message = error.get("error_user_msg") or error.get("message") or "Error de Meta"
        code = error.get("code")
        subcode = error.get("error_subcode")
        details = {"code": code, "subcode": subcode, "type": error.get("type")}
        platform_code = f"{code}/{subcode}" if subcode else str(code)

        if subcode in _MEDIA_ERROR_SUBCODES:
            return InvalidVideoError(
                message,
                http_status=response.status_code,
                platform_code=platform_code,
                details=details,
            )
        if code in _RATE_LIMIT_CODES:
            return RateLimitError(
                message,
                http_status=response.status_code,
                platform_code=platform_code,
                retry_after=parse_retry_after(response) or 900,
                details=details,
            )
        if code in _AUTH_ERROR_CODES:
            return AuthenticationError(
                message,
                http_status=response.status_code,
                platform_code=platform_code,
                details=details,
            )
        if code == 1 or code == 2:  # API unknown / API service
            return TransientProviderError(
                message,
                http_status=response.status_code,
                platform_code=platform_code,
                details=details,
            )
        if response.status_code >= 500:
            return TransientProviderError(
                message,
                http_status=response.status_code,
                platform_code=platform_code,
                details=details,
            )
        return PermanentProviderError(
            message, http_status=response.status_code, platform_code=platform_code, details=details
        )

    def _get(self, client: httpx.Client, path: str, *, stage: str, **params: Any) -> dict[str, Any]:
        response = request(
            client,
            "GET",
            f"{self.graph_base}{path}",
            stage=stage,
            params=params,
            error_parser=self._parse_error,
        )
        return json_body(response)

    def _post(self, client: httpx.Client, path: str, *, stage: str, **data: Any) -> dict[str, Any]:
        response = request(
            client,
            "POST",
            f"{self.graph_base}{path}",
            stage=stage,
            data=data,
            error_parser=self._parse_error,
        )
        return json_body(response)

    # --------------------------------------------------------------- OAuth
    def build_authorization_request(self, *, state: str, redirect_uri: str) -> AuthorizationRequest:
        """Paso 1 de `connect()`: URL del diálogo de autorización."""
        self._require_config()
        scopes = settings.instagram_scope_list
        if self.uses_instagram_login:
            # Business Login for Instagram
            params = {
                "client_id": settings.instagram_app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(scopes),
                "state": state,
            }
            url = f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"
        else:
            # Facebook Login for Business
            params = {
                "client_id": settings.instagram_app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(scopes),
                "state": state,
            }
            url = (
                f"https://www.facebook.com/{settings.instagram_graph_version}"
                f"/dialog/oauth?{urlencode(params)}"
            )
        return AuthorizationRequest(
            url=url, state=state, extra={"mode": settings.instagram_login_mode}
        )

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,  # noqa: ARG002 - Instagram no usa PKCE
    ) -> OAuthCredentials:
        """Paso 2 de `connect()`: code → access token de larga duración (60 días)."""
        self._require_config()
        with build_client() as client:
            if self.uses_instagram_login:
                short = json_body(
                    request(
                        client,
                        "POST",
                        "https://api.instagram.com/oauth/access_token",
                        stage="instagram.oauth.exchange_code",
                        data={
                            "client_id": settings.instagram_app_id,
                            "client_secret": settings.instagram_app_secret,
                            "grant_type": "authorization_code",
                            "redirect_uri": redirect_uri,
                            "code": code,
                        },
                        error_parser=self._parse_error,
                    )
                )
                short_token = short.get("access_token")
                if not short_token:
                    raise PermanentProviderError(
                        "Instagram no devolvió access_token al canjear el code"
                    )
                # Token de larga duración (60 días)
                long_lived = json_body(
                    request(
                        client,
                        "GET",
                        f"{settings.instagram_graph_base.rstrip('/')}/access_token",
                        stage="instagram.oauth.long_lived",
                        params={
                            "grant_type": "ig_exchange_token",
                            "client_secret": settings.instagram_app_secret,
                            "access_token": short_token,
                        },
                        error_parser=self._parse_error,
                    )
                )
                access_token = long_lived.get("access_token", short_token)
                expires_in = int(long_lived.get("expires_in") or 60 * 24 * 3600)
                permissions = short.get("permissions") or ""
                scopes = (
                    permissions.split(",")
                    if isinstance(permissions, str) and permissions
                    else settings.instagram_scope_list
                )
                metadata: dict[str, Any] = {
                    "login_mode": "instagram",
                    "user_id": str(short.get("user_id") or ""),
                }
            else:
                short = self._get(
                    client,
                    "/oauth/access_token",
                    stage="instagram.oauth.exchange_code",
                    client_id=settings.instagram_app_id,
                    client_secret=settings.instagram_app_secret,
                    redirect_uri=redirect_uri,
                    code=code,
                )
                short_token = short.get("access_token")
                if not short_token:
                    raise PermanentProviderError("Meta no devolvió access_token")
                long_lived = self._get(
                    client,
                    "/oauth/access_token",
                    stage="instagram.oauth.long_lived",
                    grant_type="fb_exchange_token",
                    client_id=settings.instagram_app_id,
                    client_secret=settings.instagram_app_secret,
                    fb_exchange_token=short_token,
                )
                access_token = long_lived.get("access_token", short_token)
                expires_in = int(long_lived.get("expires_in") or 60 * 24 * 3600)
                scopes = settings.instagram_scope_list
                metadata = {"login_mode": "facebook"}

            return OAuthCredentials(
                access_token=access_token,
                expires_at=utcnow() + timedelta(seconds=expires_in),
                scopes=[s for s in scopes if s],
                metadata=metadata,
            )

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Renueva el token de 60 días.

        Instagram no usa refresh tokens: se intercambia el propio token de
        larga duración por otro nuevo, siempre que tenga más de 24 h de vida
        y menos de 60 días. Si ya caducó hay que reconectar la cuenta.
        """
        self._require_config()
        with build_client() as client:
            if (
                credentials.metadata.get("login_mode") == "facebook"
                or not self.uses_instagram_login
            ):
                data = self._get(
                    client,
                    "/oauth/access_token",
                    stage="instagram.oauth.refresh",
                    grant_type="fb_exchange_token",
                    client_id=settings.instagram_app_id,
                    client_secret=settings.instagram_app_secret,
                    fb_exchange_token=credentials.access_token,
                )
            else:
                data = json_body(
                    request(
                        client,
                        "GET",
                        f"{settings.instagram_graph_base.rstrip('/')}/refresh_access_token",
                        stage="instagram.oauth.refresh",
                        params={
                            "grant_type": "ig_refresh_token",
                            "access_token": credentials.access_token,
                        },
                        error_parser=self._parse_error,
                    )
                )
        token = data.get("access_token")
        if not token:
            raise AuthenticationError(
                "No se pudo renovar el token de Instagram; reconecta la cuenta"
            )
        expires_in = int(data.get("expires_in") or 60 * 24 * 3600)
        return OAuthCredentials(
            access_token=token,
            expires_at=utcnow() + timedelta(seconds=expires_in),
            scopes=credentials.scopes,
            metadata=credentials.metadata,
        )

    # -------------------------------------------------------------- cuenta
    def get_account(self, credentials: OAuthCredentials) -> AccountInfo:
        """Devuelve el IG User ID profesional y valida el tipo de cuenta."""
        with build_client() as client:
            if (
                credentials.metadata.get("login_mode") == "facebook"
                or not self.uses_instagram_login
            ):
                return self._get_account_via_facebook(client, credentials)
            return self._get_account_via_instagram(client, credentials)

    def _get_account_via_instagram(
        self, client: httpx.Client, credentials: OAuthCredentials
    ) -> AccountInfo:
        data = self._get(
            client,
            "/me",
            stage="instagram.get_account",
            fields="user_id,username,account_type,media_count,followers_count,profile_picture_url",
            access_token=credentials.access_token,
        )
        ig_id = str(data.get("user_id") or data.get("id") or "")
        if not ig_id:
            raise PermanentProviderError("Instagram no devolvió el user_id de la cuenta")
        account_type = str(data.get("account_type") or "").upper()
        if account_type and account_type not in {"BUSINESS", "MEDIA_CREATOR", "CREATOR"}:
            raise PermanentProviderError(
                "La cuenta de Instagram debe ser Professional (Business o Creator) "
                f"para publicar por API. Tipo detectado: {account_type}. "
                "Cámbialo en la app de Instagram: Configuración → Tipo de cuenta."
            )
        return AccountInfo(
            external_account_id=ig_id,
            account_name=str(data.get("username") or ig_id),
            metadata={
                "login_mode": "instagram",
                "account_type": account_type or "UNKNOWN",
                "media_count": data.get("media_count"),
                "followers_count": data.get("followers_count"),
                "profile_picture_url": data.get("profile_picture_url"),
            },
        )

    def _get_account_via_facebook(
        self, client: httpx.Client, credentials: OAuthCredentials
    ) -> AccountInfo:
        """Localiza la cuenta IG Business a través de la Página de Facebook."""
        pages = self._get(
            client,
            "/me/accounts",
            stage="instagram.get_account.pages",
            fields="id,name,access_token,instagram_business_account{id,username}",
            access_token=credentials.access_token,
        )
        for page in pages.get("data", []):
            ig = page.get("instagram_business_account")
            if not ig:
                continue
            return AccountInfo(
                external_account_id=str(ig["id"]),
                account_name=str(ig.get("username") or page.get("name") or ig["id"]),
                metadata={
                    "login_mode": "facebook",
                    "page_id": page.get("id"),
                    "page_name": page.get("name"),
                    # El token de Página es el que hay que usar para publicar.
                    "page_access_token_present": bool(page.get("access_token")),
                    "page_access_token": page.get("access_token"),
                    "account_type": "BUSINESS",
                },
            )
        raise PermanentProviderError(
            "Ninguna Página de Facebook del usuario tiene una cuenta de Instagram "
            "Professional vinculada. Vincúlala en: Página → Configuración → Instagram."
        )

    @staticmethod
    def _publishing_token(credentials: OAuthCredentials) -> str:
        """Con Facebook Login hay que publicar con el token de Página."""
        page_token = credentials.metadata.get("page_access_token")
        if credentials.metadata.get("login_mode") == "facebook" and page_token:
            return str(page_token)
        return credentials.access_token

    # ------------------------------------------------------------ límites
    def get_publishing_limit(
        self, credentials: OAuthCredentials, ig_user_id: str
    ) -> dict[str, Any]:
        """`GET /<IG_ID>/content_publishing_limit` — cuota de 24 h."""
        with build_client() as client:
            data = self._get(
                client,
                f"/{ig_user_id}/content_publishing_limit",
                stage="instagram.publishing_limit",
                fields="config,quota_usage",
                access_token=self._publishing_token(credentials),
            )
        entries = data.get("data") or [{}]
        return entries[0] if isinstance(entries, list) and entries else {}

    # ------------------------------------------------------- publicación
    def create_media_container(
        self,
        credentials: OAuthCredentials,
        ig_user_id: str,
        *,
        media_type: str = "REELS",
        video_url: str | None = None,
        caption: str | None = None,
        resumable: bool = False,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Paso 1: crea el contenedor y devuelve su `IG_CONTAINER_ID`."""
        options = options or {}
        payload: dict[str, Any] = {
            "media_type": media_type,
            "access_token": self._publishing_token(credentials),
        }
        if caption:
            payload["caption"] = caption[:2200]
        if resumable:
            payload["upload_type"] = "resumable"
        elif video_url:
            payload["video_url"] = video_url
        else:
            raise ConfigurationError(
                "Instagram necesita una URL pública del video o el modo resumable"
            )

        for key in (
            "cover_url",
            "thumb_offset",
            "share_to_feed",
            "collaborators",
            "location_id",
            "audio_name",
            "alt_text",
        ):
            if options.get(key) is not None:
                payload[key] = options[key]

        with build_client() as client:
            data = self._post(
                client,
                f"/{ig_user_id}/media",
                stage="instagram.create_media_container",
                **payload,
            )
        container_id = data.get("id")
        if not container_id:
            raise PermanentProviderError("Instagram no devolvió el id del contenedor de media")
        logger.info("instagram: contenedor creado container_id=%s", container_id)
        return str(container_id)

    def upload_video(
        self,
        credentials: OAuthCredentials,
        container_id: str,
        *,
        data: bytes | None = None,
        file_url: str | None = None,
        size_bytes: int | None = None,
    ) -> None:
        """Paso 1b: subida resumible a `rupload.facebook.com`.

        Requiere que el contenedor se haya creado con `upload_type=resumable`.
        Headers obligatorios: `Authorization: OAuth <token>`, `offset`, `file_size`.
        """
        if data is None and not file_url:
            raise ConfigurationError("upload_video necesita `data` o `file_url`")

        headers = {
            "Authorization": f"OAuth {self._publishing_token(credentials)}",
            "offset": "0",
        }
        content: bytes | None = None
        if data is not None:
            headers["file_size"] = str(len(data))
            content = data
        else:
            headers["file_url"] = str(file_url)
            if size_bytes:
                headers["file_size"] = str(size_bytes)

        url = f"{self.rupload_base}/{container_id}"
        with build_client(timeout=settings.upload_timeout_seconds) as client:
            response = request(
                client,
                "POST",
                url,
                stage="instagram.upload_video",
                headers=headers,
                content=content,
                error_parser=self._parse_error,
            )
        body = json_body(response)
        if body and body.get("success") is False:
            raise TransientProviderError(
                f"La subida a Instagram no fue aceptada: {body}",
                stage="instagram.upload_video",
            )
        logger.info("instagram: video subido container_id=%s", container_id)

    def check_container_status(
        self, credentials: OAuthCredentials, container_id: str
    ) -> RemoteStatus:
        """Paso 2: `GET /<CONTAINER_ID>?fields=status_code`.

        `status_code` ∈ {EXPIRED, ERROR, FINISHED, IN_PROGRESS, PUBLISHED}.
        """
        with build_client() as client:
            data = self._get(
                client,
                f"/{container_id}",
                stage="instagram.check_container_status",
                fields="status_code,status",
                access_token=self._publishing_token(credentials),
            )
        code = str(data.get("status_code") or "IN_PROGRESS").upper()
        return RemoteStatus(
            state=code,
            is_final=code in {"FINISHED", "PUBLISHED", "ERROR", "EXPIRED"},
            raw=data,
        )

    def wait_for_container(self, credentials: OAuthCredentials, container_id: str) -> None:
        """Espera a `FINISHED` con polling controlado (no agresivo)."""
        last = "IN_PROGRESS"
        for _tick in poll_ticks(
            timeout_seconds=settings.processing_timeout_seconds,
            interval_seconds=settings.processing_poll_interval_seconds,
        ):
            status = self.check_container_status(credentials, container_id)
            last = status.state
            if status.state in {"FINISHED", "PUBLISHED"}:
                return
            if status.state == "ERROR":
                detail = status.raw.get("status") or ""
                raise InvalidVideoError(
                    f"Instagram no pudo procesar el video: {detail or 'status_code=ERROR'}",
                    stage="instagram.processing",
                    details=status.raw,
                )
            if status.state == "EXPIRED":
                raise PermanentProviderError(
                    "El contenedor de Instagram expiró antes de publicarse "
                    "(los contenedores caducan a las 24 h)",
                    stage="instagram.processing",
                )
        raise ProcessingTimeoutError(
            f"Instagram sigue procesando el video tras "
            f"{settings.processing_timeout_seconds}s (último estado: {last})",
            stage="instagram.processing",
        )

    def publish_container(
        self, credentials: OAuthCredentials, ig_user_id: str, container_id: str
    ) -> str:
        """Paso 3: `POST /<IG_ID>/media_publish` → devuelve el IG media id."""
        with build_client() as client:
            data = self._post(
                client,
                f"/{ig_user_id}/media_publish",
                stage="instagram.publish",
                creation_id=container_id,
                access_token=self._publishing_token(credentials),
            )
        media_id = data.get("id")
        if not media_id:
            raise PermanentProviderError("Instagram no devolvió el id del post publicado")
        return str(media_id)

    def publish(self, credentials: OAuthCredentials, request_data: PublishRequest) -> PublishResult:
        """Orquesta los 3 pasos. Reanudable: reutiliza el container_id guardado."""
        self._require_config()
        ig_user_id = str(
            request_data.options.get("ig_user_id")
            or credentials.metadata.get("external_account_id")
            or ""
        )
        if not ig_user_id:
            raise ConfigurationError("Falta el IG user id de la cuenta de Instagram")

        video = request_data.video
        container_id = request_data.state.get("container_id")

        if not container_id:
            request_data.set_stage("uploading")
            use_resumable = not video.public_url
            container_id = self.create_media_container(
                credentials,
                ig_user_id,
                media_type=str(request_data.options.get("media_type", "REELS")),
                video_url=video.public_url,
                caption=request_data.caption,
                resumable=use_resumable,
                options=request_data.options,
            )
            request_data.save_state(container_id=container_id, uploaded=not use_resumable)

            if use_resumable:
                if not video.has_stream:
                    raise ConfigurationError(
                        "Sin URL pública ni fichero local no se puede subir a Instagram"
                    )
                payload = self._read_all(video)
                self.upload_video(credentials, container_id, data=payload)
                request_data.save_state(uploaded=True)

        request_data.set_stage("processing")
        self.wait_for_container(credentials, container_id)

        request_data.set_stage("publishing")
        media_id = self.publish_container(credentials, ig_user_id, container_id)
        permalink = self._fetch_permalink(credentials, media_id)
        return PublishResult(
            external_post_id=media_id,
            external_url=permalink,
            metadata={"container_id": container_id, "ig_user_id": ig_user_id},
        )

    @staticmethod
    def _read_all(video: Any) -> bytes:
        """Lee el video completo en memoria (Instagram exige el fichero entero)."""
        if video.local_path:
            with Path(video.local_path).open("rb") as handle:
                return handle.read()
        if video.open_stream:
            return b"".join(video.open_stream())
        raise ConfigurationError("El video no tiene contenido accesible")

    def _fetch_permalink(self, credentials: OAuthCredentials, media_id: str) -> str | None:
        try:
            with build_client() as client:
                data = self._get(
                    client,
                    f"/{media_id}",
                    stage="instagram.permalink",
                    fields="permalink",
                    access_token=self._publishing_token(credentials),
                )
            return data.get("permalink")
        except ProviderError as exc:  # el permalink es informativo, no crítico
            logger.warning("instagram: no se pudo obtener permalink: %s", exc)
            return None

    def get_post_status(self, credentials: OAuthCredentials, external_post_id: str) -> RemoteStatus:
        with build_client() as client:
            data = self._get(
                client,
                f"/{external_post_id}",
                stage="instagram.get_post_status",
                fields="id,permalink,media_type,timestamp",
                access_token=self._publishing_token(credentials),
            )
        return RemoteStatus(
            state="PUBLISHED" if data.get("id") else "UNKNOWN",
            is_final=bool(data.get("id")),
            external_url=data.get("permalink"),
            raw=data,
        )
