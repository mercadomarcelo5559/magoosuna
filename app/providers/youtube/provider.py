"""YouTubeProvider — YouTube Data API v3 oficial.

Documentación de referencia (consultada para esta implementación):
  * https://developers.google.com/youtube/v3/docs/videos/insert
  * https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
  * https://developers.google.com/youtube/v3/docs/channels/list
  * https://developers.google.com/identity/protocols/oauth2/web-server

Endpoints usados:
  * GET  https://accounts.google.com/o/oauth2/v2/auth       → consentimiento
  * POST https://oauth2.googleapis.com/token                → tokens / refresh
  * POST https://oauth2.googleapis.com/revoke               → revocar
  * GET  /youtube/v3/channels?mine=true                     → canal
  * POST /upload/youtube/v3/videos?uploadType=resumable     → videos.insert
  * GET  /youtube/v3/videos?part=status,processingDetails    → estado

Notas de la plataforma:
  * Scopes: `youtube.upload` (subir) y `youtube.readonly` (leer canal).
  * `access_type=offline` + `prompt=consent` son necesarios para recibir
    refresh token.
  * Cuota: videos.insert cuesta 1600 unidades; la cuota diaria por defecto es
    10 000 unidades (≈6 subidas/día) y se amplía solicitándolo a Google.
  * Proyectos sin verificar (creados después del 28/07/2020) sólo pueden
    subir videos en modo **private** hasta pasar la auditoría de Google.
  * Shorts: no hay endpoint especial. Se sube con el flujo normal; YouTube lo
    clasifica como Short si es vertical y de <= 3 minutos.
"""

from __future__ import annotations

import json
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
    ErrorContext,
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

#: Tamaño de chunk para la subida resumible. Múltiplo de 256 KiB (exigido).
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024

_QUOTA_REASONS = {
    "quotaExceeded",
    "dailyLimitExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "uploadLimitExceeded",
}
_AUTH_REASONS = {
    "authError",
    "forbidden",
    "insufficientPermissions",
    "youtubeSignupRequired",
    "unauthorized",
}
# Nota: `uploadLimitExceeded` (demasiados videos subidos por el usuario) es un
# límite de cuota reintentable, así que va en _QUOTA_REASONS, no aquí.
_VIDEO_REASONS = {
    "invalidVideoMetadata",
    "mediaBodyRequired",
    "invalidFilename",
    "invalidVideoTitle",
    "invalidDescription",
    "invalidTags",
    "invalidCategoryId",
    "failedPrecondition",
    "videoTooLong",
    "invalidRecordingDetails",
}


class YouTubeProvider(BaseProvider):
    platform: ClassVar[Platform] = Platform.YOUTUBE
    setup_docs_url: ClassVar[str] = "https://developers.google.com/youtube/v3/docs/videos/insert"

    # ------------------------------------------------------------- config
    def is_configured(self) -> bool:
        return bool(settings.youtube_client_id and settings.youtube_client_secret)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise ConfigurationError(
                "YouTube no está configurado: define YOUTUBE_CLIENT_ID y "
                "YOUTUBE_CLIENT_SECRET en el .env (credenciales OAuth de tipo "
                "'Aplicación web' en https://console.cloud.google.com/apis/credentials)"
            )

    # ----------------------------------------------------- errores Google
    @staticmethod
    def _parse_error(response: httpx.Response) -> ProviderError | None:
        payload = json_body(response)
        error = payload.get("error")
        if isinstance(error, str):
            message = payload.get("error_description") or error
            if error in {"invalid_grant", "unauthorized_client", "invalid_client"}:
                return AuthenticationError(
                    f"{message} (reconecta el canal de YouTube)",
                    http_status=response.status_code,
                    platform_code=error,
                )
            return PermanentProviderError(
                message, http_status=response.status_code, platform_code=error
            )
        if not isinstance(error, dict):
            return None

        message = error.get("message") or "Error de YouTube"
        errors = error.get("errors") or []
        reason = errors[0].get("reason") if errors and isinstance(errors[0], dict) else None
        details: dict[str, Any] = {"reason": reason, "status": error.get("status")}
        contexto: ErrorContext = {
            "http_status": response.status_code,
            "platform_code": str(reason) if reason else None,
            "details": details,
        }

        if reason in _QUOTA_REASONS:
            return RateLimitError(
                f"{message} (cuota de la YouTube Data API; revisa "
                f"https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas)",
                retry_after=parse_retry_after(response) or 3600,
                **contexto,
            )
        if reason in _VIDEO_REASONS:
            return InvalidVideoError(message, **contexto)
        if reason in _AUTH_REASONS or response.status_code in (401, 403):
            return AuthenticationError(message, **contexto)
        if response.status_code >= 500 or reason == "backendError":
            return TransientProviderError(message, **contexto)
        return PermanentProviderError(message, **contexto)

    # --------------------------------------------------------------- OAuth
    def build_authorization_request(self, *, state: str, redirect_uri: str) -> AuthorizationRequest:
        self._require_config()
        params = {
            "client_id": settings.youtube_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(settings.youtube_scope_list),
            "access_type": "offline",  # necesario para obtener refresh_token
            "prompt": "consent",  # fuerza refresh_token en re-autorizaciones
            "include_granted_scopes": "true",
            "state": state,
        }
        url = f"{settings.youtube_oauth_auth_url}?{urlencode(params)}"
        return AuthorizationRequest(url=url, state=state)

    def _token_request(self, data: dict[str, str], *, stage: str) -> dict[str, Any]:
        with build_client() as client:
            response = request(
                client,
                "POST",
                settings.youtube_oauth_token_url,
                stage=stage,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=data,
                error_parser=self._parse_error,
            )
        return json_body(response)

    def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> OAuthCredentials:
        self._require_config()
        data = {
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        payload = self._token_request(data, stage="youtube.oauth.exchange_code")

        access_token = payload.get("access_token")
        if not access_token:
            raise AuthenticationError("Google no devolvió access_token")
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise AuthenticationError(
                "Google no devolvió refresh_token. Revoca el acceso de la app en "
                "https://myaccount.google.com/permissions y vuelve a conectar "
                "(la API pide access_type=offline y prompt=consent)."
            )
        return OAuthCredentials(
            access_token=str(access_token),
            refresh_token=str(refresh_token),
            expires_at=utcnow() + timedelta(seconds=int(payload.get("expires_in") or 3600)),
            scopes=str(payload.get("scope") or "").split(),
            metadata={"token_type": payload.get("token_type", "Bearer")},
        )

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Renueva el access token (1 h) usando el refresh token (sin caducidad)."""
        self._require_config()
        if not credentials.refresh_token:
            raise AuthenticationError("El canal de YouTube no tiene refresh token; reconéctalo")
        payload = self._token_request(
            {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": credentials.refresh_token,
                "grant_type": "refresh_token",
            },
            stage="youtube.oauth.refresh",
        )
        access_token = payload.get("access_token")
        if not access_token:
            raise AuthenticationError("Google no devolvió un access_token renovado")
        return OAuthCredentials(
            access_token=str(access_token),
            # Google no rota el refresh token en cada refresh.
            refresh_token=payload.get("refresh_token") or credentials.refresh_token,
            expires_at=utcnow() + timedelta(seconds=int(payload.get("expires_in") or 3600)),
            scopes=str(payload.get("scope") or "").split() or credentials.scopes,
            metadata=credentials.metadata,
        )

    def revoke(self, credentials: OAuthCredentials) -> None:
        try:
            with build_client() as client:
                request(
                    client,
                    "POST",
                    "https://oauth2.googleapis.com/revoke",
                    stage="youtube.oauth.revoke",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={"token": credentials.refresh_token or credentials.access_token},
                    error_parser=self._parse_error,
                )
        except ProviderError as exc:
            logger.warning("youtube: no se pudo revocar el token: %s", exc)

    # ------------------------------------------------------------- canal
    def get_account(self, credentials: OAuthCredentials) -> AccountInfo:
        """`GET /channels?mine=true` — id y nombre del canal."""
        with build_client() as client:
            response = request(
                client,
                "GET",
                f"{settings.youtube_api_base}/channels",
                stage="youtube.get_account",
                params={"part": "snippet,contentDetails,statistics", "mine": "true"},
                headers=self._auth_headers(credentials),
                error_parser=self._parse_error,
            )
        data = json_body(response)
        items = data.get("items") or []
        if not items:
            raise PermanentProviderError(
                "La cuenta de Google autorizada no tiene ningún canal de YouTube. "
                "Crea el canal en https://www.youtube.com/create_channel y reconecta."
            )
        channel = items[0]
        snippet = channel.get("snippet") or {}
        return AccountInfo(
            external_account_id=str(channel["id"]),
            account_name=str(snippet.get("title") or channel["id"]),
            metadata={
                "custom_url": snippet.get("customUrl"),
                "thumbnail": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url"),
                "uploads_playlist": (
                    (channel.get("contentDetails") or {}).get("relatedPlaylists") or {}
                ).get("uploads"),
                "subscriber_count": (channel.get("statistics") or {}).get("subscriberCount"),
            },
        )

    @staticmethod
    def _auth_headers(credentials: OAuthCredentials) -> dict[str, str]:
        return {"Authorization": f"Bearer {credentials.access_token}"}

    # ------------------------------------------------------------ publish
    def _build_body(self, request_data: PublishRequest) -> dict[str, Any]:
        options = request_data.options
        title = (request_data.title or request_data.caption or "Video")[:100]
        description = (request_data.description or request_data.caption or "")[:5000]
        privacy = str(options.get("privacy_status") or settings.youtube_default_privacy)
        if privacy not in {"private", "unlisted", "public"}:
            raise ConfigurationError(f"privacy_status inválido para YouTube: {privacy}")

        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
            "categoryId": str(options.get("category_id") or settings.youtube_default_category_id),
        }
        tags = request_data.tags or []
        if tags:
            # YouTube limita los tags a 500 caracteres en total.
            selected: list[str] = []
            budget = 500
            for tag in tags:
                cost = len(tag) + 1
                if cost > budget:
                    break
                selected.append(tag)
                budget -= cost
            snippet["tags"] = selected
        if options.get("default_language"):
            snippet["defaultLanguage"] = options["default_language"]

        status: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(options.get("made_for_kids", False)),
            "embeddable": bool(options.get("embeddable", True)),
            "license": str(options.get("license") or "youtube"),
        }
        if options.get("publish_at"):
            # publishAt exige privacyStatus=private hasta la hora indicada.
            status["privacyStatus"] = "private"
            status["publishAt"] = options["publish_at"]
        if options.get("contains_synthetic_media") is not None:
            status["containsSyntheticMedia"] = bool(options["contains_synthetic_media"])

        return {"snippet": snippet, "status": status}

    def create_upload_session(
        self, credentials: OAuthCredentials, request_data: PublishRequest
    ) -> str:
        """Inicia la subida resumible y devuelve la URL de sesión (header Location)."""
        body = self._build_body(request_data)
        params = {
            "uploadType": "resumable",
            "part": "snippet,status",
            "notifySubscribers": str(
                bool(request_data.options.get("notify_subscribers", True))
            ).lower(),
        }
        headers = {
            **self._auth_headers(credentials),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(request_data.video.size_bytes),
            "X-Upload-Content-Type": request_data.video.content_type or "video/*",
        }
        with build_client() as client:
            response = request(
                client,
                "POST",
                f"{settings.youtube_upload_base}/videos",
                stage="youtube.create_upload_session",
                params=params,
                headers=headers,
                content=json.dumps(body).encode(),
                error_parser=self._parse_error,
            )
        location = response.headers.get("location") or response.headers.get("Location")
        if not location:
            raise TransientProviderError(
                "YouTube no devolvió la URL de sesión de subida",
                stage="youtube.create_upload_session",
            )
        return location

    def upload_video(self, session_url: str, request_data: PublishRequest) -> dict[str, Any]:
        """Sube el fichero por chunks de 8 MiB con `Content-Range`."""
        video = request_data.video
        total = video.size_bytes
        if total <= 0:
            raise InvalidVideoError("El video está vacío")

        with build_client(timeout=settings.upload_timeout_seconds) as client:
            for offset, chunk in self._iter_chunks(video, total):
                last = offset + len(chunk) - 1
                try:
                    response = client.put(
                        session_url,
                        content=chunk,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{last}/{total}",
                        },
                    )
                except httpx.TimeoutException as exc:
                    raise TransientProviderError(
                        f"Timeout subiendo a YouTube: {exc}", stage="youtube.upload_video"
                    ) from exc
                except httpx.TransportError as exc:
                    raise TransientProviderError(
                        f"Error de red subiendo a YouTube: {exc}", stage="youtube.upload_video"
                    ) from exc

                # 308 = Resume Incomplete: el chunk se aceptó, seguimos.
                if response.status_code == 308:
                    continue
                if response.is_success:
                    return json_body(response)
                parsed = self._parse_error(response)
                if parsed:
                    parsed.stage = "youtube.upload_video"
                    raise parsed
                raise TransientProviderError(
                    f"YouTube rechazó el chunk ({response.status_code}): " f"{response.text[:300]}",
                    stage="youtube.upload_video",
                    http_status=response.status_code,
                )
        raise TransientProviderError(
            "La subida a YouTube terminó sin respuesta final",
            stage="youtube.upload_video",
        )

    @staticmethod
    def _iter_chunks(video: Any, total: int):
        """Genera `(offset, bytes)` en múltiplos de 256 KiB salvo el último."""
        if video.local_path:
            with Path(video.local_path).open("rb") as handle:
                offset = 0
                while offset < total:
                    data = handle.read(UPLOAD_CHUNK_SIZE)
                    if not data:
                        break
                    yield offset, data
                    offset += len(data)
            return
        if not video.open_stream:
            raise ConfigurationError("El video no tiene contenido accesible")
        buffer = bytearray()
        offset = 0
        for piece in video.open_stream():
            buffer.extend(piece)
            while len(buffer) >= UPLOAD_CHUNK_SIZE:
                data = bytes(buffer[:UPLOAD_CHUNK_SIZE])
                del buffer[:UPLOAD_CHUNK_SIZE]
                yield offset, data
                offset += len(data)
        if buffer:
            yield offset, bytes(buffer)

    def publish(self, credentials: OAuthCredentials, request_data: PublishRequest) -> PublishResult:
        """videos.insert resumible. Reanudable vía `session_url` persistida."""
        self._require_config()
        if not request_data.video.has_stream:
            raise ConfigurationError(
                "YouTube requiere el fichero de video (no acepta publicar desde URL). "
                "Sube el fichero a /v1/media o deja que la API lo descargue de la URL."
            )

        session_url = request_data.state.get("session_url")
        if not session_url:
            request_data.set_stage("uploading")
            session_url = self.create_upload_session(credentials, request_data)
            request_data.save_state(session_url=session_url)

        video_resource = request_data.state.get("video_resource")
        if not video_resource:
            request_data.set_stage("uploading")
            video_resource = self.upload_video(str(session_url), request_data)
            request_data.save_state(video_resource={"id": video_resource.get("id")})

        video_id = video_resource.get("id")
        if not video_id:
            raise TransientProviderError(
                "YouTube no devolvió el id del video", stage="youtube.publish"
            )

        request_data.set_stage("processing")
        status = self.wait_for_processing(credentials, str(video_id))
        return PublishResult(
            external_post_id=str(video_id),
            external_url=f"https://www.youtube.com/watch?v={video_id}",
            metadata={
                "upload_status": status.state,
                "privacy_status": status.raw.get("privacyStatus"),
                "short_url": f"https://youtu.be/{video_id}",
            },
        )

    def wait_for_processing(self, credentials: OAuthCredentials, video_id: str) -> RemoteStatus:
        """Espera a que YouTube termine de procesar (`uploadStatus=processed`)."""
        last: RemoteStatus | None = None
        for _tick in poll_ticks(
            timeout_seconds=settings.processing_timeout_seconds,
            interval_seconds=settings.processing_poll_interval_seconds,
        ):
            last = self.get_post_status(credentials, video_id)
            if last.state == "processed":
                return last
            if last.state in {"failed", "rejected"}:
                reason = last.raw.get("failureReason") or last.raw.get("rejectionReason") or "?"
                raise InvalidVideoError(
                    f"YouTube rechazó el video: {reason}",
                    stage="youtube.processing",
                    platform_code=str(reason),
                    details=last.raw,
                )
            if last.state == "deleted":
                raise PermanentProviderError(
                    "El video fue borrado en YouTube", stage="youtube.processing"
                )
        # El video ya existe: el timeout de procesado no invalida la publicación.
        raise ProcessingTimeoutError(
            f"YouTube sigue procesando el video {video_id} tras "
            f"{settings.processing_timeout_seconds}s",
            stage="youtube.processing",
            details={"video_id": video_id, "last_state": last.state if last else None},
        )

    def get_post_status(self, credentials: OAuthCredentials, external_post_id: str) -> RemoteStatus:
        with build_client() as client:
            response = request(
                client,
                "GET",
                f"{settings.youtube_api_base}/videos",
                stage="youtube.get_post_status",
                params={"part": "status,processingDetails,snippet", "id": external_post_id},
                headers=self._auth_headers(credentials),
                error_parser=self._parse_error,
            )
        data = json_body(response)
        items = data.get("items") or []
        if not items:
            return RemoteStatus(state="not_found", is_final=True, raw={})
        status = items[0].get("status") or {}
        upload_status = str(status.get("uploadStatus") or "uploaded")
        return RemoteStatus(
            state=upload_status,
            is_final=upload_status in {"processed", "failed", "rejected", "deleted"},
            external_url=f"https://www.youtube.com/watch?v={external_post_id}",
            raw={
                **status,
                "processingStatus": (items[0].get("processingDetails") or {}).get(
                    "processingStatus"
                ),
            },
        )
