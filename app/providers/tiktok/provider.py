"""TikTokProvider — Content Posting API v2 oficial de TikTok.

Documentación de referencia (consultada para esta implementación):
  * https://developers.tiktok.com/doc/content-posting-api-get-started/
  * https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
  * https://developers.tiktok.com/doc/content-posting-api-reference-upload-video/
  * https://developers.tiktok.com/doc/oauth-user-access-token-management
  * https://developers.tiktok.com/doc/login-kit-overview/

Endpoints usados (host https://open.tiktokapis.com):
  * POST /v2/oauth/token/                        → tokens
  * POST /v2/oauth/revoke/                       → revocar
  * POST /v2/post/publish/creator_info/query/    → creator info (obligatorio antes de publicar)
  * POST /v2/post/publish/video/init/            → Direct Post
  * POST /v2/post/publish/inbox/video/init/      → Upload a borradores (inbox)
  * PUT  <upload_url>                            → subida por chunks
  * POST /v2/post/publish/status/fetch/          → estado

AUDITORÍA / APROBACIÓN (requisito real de TikTok, no se puede sortear):
  * Se necesita una app en https://developers.tiktok.com con el producto
    "Content Posting API" añadido y los scopes `video.publish` (Direct Post)
    y/o `video.upload` (inbox) aprobados.
  * Mientras la app NO haya pasado el *audit* de TikTok, todo el contenido
    publicado queda restringido a visibilidad privada (SELF_ONLY).
  * Para Direct Post con `PULL_FROM_URL` hay que verificar la propiedad del
    dominio en el portal de developers (URL prefix verification).
  * Límite: 6 peticiones/minuto por access token en los endpoints de init.
"""

from __future__ import annotations

import math
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

#: Reglas de chunking de TikTok.
MIN_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MB
MAX_CHUNK_COUNT = 1000
#: Un fichero menor que este tamaño se sube completo en una sola petición.
WHOLE_FILE_LIMIT = MAX_CHUNK_SIZE

_AUTH_CODES = {
    "access_token_invalid",
    "scope_not_authorized",
    "scope_permission_missed",
    "token_expired",
    "unauthorized",
}
_RATE_LIMIT_CODES = {
    "rate_limit_exceeded",
    "spam_risk_too_many_posts",
    "spam_risk_user_banned_from_posting",
    "spam_risk",
}
_VIDEO_CODES = {
    "file_format_check_failed",
    "duration_check_failed",
    "frame_rate_check_failed",
    "picture_size_check_failed",
    "video_frame_rate_check_failed",
    "invalid_file_upload",
    "invalid_params",
}
_PERMANENT_CODES = {
    "privacy_level_option_mismatch",
    "url_ownership_unverified",
    "publish_attempt_limit_exceeded",
    "reached_active_user_cap",
}


class TikTokProvider(BaseProvider):
    platform: ClassVar[Platform] = Platform.TIKTOK
    setup_docs_url: ClassVar[str] = (
        "https://developers.tiktok.com/doc/content-posting-api-get-started/"
    )

    # ------------------------------------------------------------- config
    @property
    def api_base(self) -> str:
        return settings.tiktok_api_base.rstrip("/")

    def is_configured(self) -> bool:
        return bool(settings.tiktok_client_key and settings.tiktok_client_secret)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise ConfigurationError(
                "TikTok no está configurado: define TIKTOK_CLIENT_KEY y "
                "TIKTOK_CLIENT_SECRET en el .env "
                "(app en https://developers.tiktok.com/apps)"
            )

    # ------------------------------------------------------ errores TikTok
    @staticmethod
    def _parse_error(response: httpx.Response) -> ProviderError | None:
        payload = json_body(response)
        error = payload.get("error")
        if isinstance(error, str):
            # Endpoints OAuth devuelven {"error": "...", "error_description": "..."}
            code = error
            message = payload.get("error_description") or error
        elif isinstance(error, dict):
            code = str(error.get("code") or "")
            message = error.get("message") or code or "Error de TikTok"
            if code in {"ok", ""}:
                return None
        else:
            return None

        details: dict[str, Any] = {
            "code": code,
            "log_id": error.get("log_id") if isinstance(error, dict) else None,
        }
        contexto: ErrorContext = {
            "http_status": response.status_code,
            "platform_code": code,
            "details": details,
        }

        if code in _RATE_LIMIT_CODES:
            return RateLimitError(
                message, retry_after=parse_retry_after(response) or 60, **contexto
            )
        if code in _AUTH_CODES:
            return AuthenticationError(message, **contexto)
        if code in _VIDEO_CODES:
            return InvalidVideoError(message, **contexto)
        if code in _PERMANENT_CODES:
            return PermanentProviderError(message, **contexto)
        if code in {"internal_error", "service_unavailable"} or response.status_code >= 500:
            return TransientProviderError(message, **contexto)
        return PermanentProviderError(message, **contexto)

    def _api_post(
        self,
        client: httpx.Client,
        path: str,
        *,
        stage: str,
        token: str,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = request(
            client,
            "POST",
            f"{self.api_base}{path}",
            stage=stage,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=json_payload or {},
            error_parser=self._parse_error,
        )
        payload = json_body(response)
        # TikTok devuelve 200 con error.code != "ok" en algunos casos.
        error = payload.get("error")
        if isinstance(error, dict) and str(error.get("code", "ok")).lower() not in {"ok", ""}:
            parsed = self._parse_error(response)
            if parsed:
                parsed.stage = stage
                raise parsed
        return payload.get("data") or {}

    # --------------------------------------------------------------- OAuth
    def build_authorization_request(self, *, state: str, redirect_uri: str) -> AuthorizationRequest:
        """Paso 1 de `connect()`: diálogo de Login Kit."""
        self._require_config()
        params = {
            "client_key": settings.tiktok_client_key,
            "scope": ",".join(settings.tiktok_scope_list),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        url = f"{settings.tiktok_auth_base.rstrip('/')}/v2/auth/authorize/?{urlencode(params)}"
        return AuthorizationRequest(url=url, state=state)

    def _token_request(self, data: dict[str, str], *, stage: str) -> OAuthCredentials:
        with build_client() as client:
            response = request(
                client,
                "POST",
                f"{self.api_base}/v2/oauth/token/",
                stage=stage,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cache-Control": "no-cache",
                },
                data=data,
                error_parser=self._parse_error,
            )
        payload = json_body(response)
        if payload.get("error") and payload.get("error") != "ok":
            raise AuthenticationError(
                str(payload.get("error_description") or payload.get("error")),
                platform_code=str(payload.get("error")),
                stage=stage,
            )
        access_token = payload.get("access_token")
        if not access_token:
            raise AuthenticationError("TikTok no devolvió access_token", stage=stage)

        expires_in = int(payload.get("expires_in") or 86400)
        refresh_expires_in = int(payload.get("refresh_expires_in") or 365 * 86400)
        scope_raw = payload.get("scope") or ""
        return OAuthCredentials(
            access_token=str(access_token),
            refresh_token=payload.get("refresh_token"),
            expires_at=utcnow() + timedelta(seconds=expires_in),
            refresh_expires_at=utcnow() + timedelta(seconds=refresh_expires_in),
            scopes=[s for s in str(scope_raw).replace(" ", "").split(",") if s],
            metadata={"open_id": payload.get("open_id")},
        )

    def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> OAuthCredentials:
        """Paso 2 de `connect()`: code → access token (24 h) + refresh (365 d)."""
        self._require_config()
        data = {
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        return self._token_request(data, stage="tiktok.oauth.exchange_code")

    def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        self._require_config()
        if not credentials.refresh_token:
            raise AuthenticationError("La cuenta de TikTok no tiene refresh token; reconéctala")
        refreshed = self._token_request(
            {
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": credentials.refresh_token,
            },
            stage="tiktok.oauth.refresh",
        )
        # Conservamos metadata previa (open_id, username…)
        merged = dict(credentials.metadata)
        merged.update({k: v for k, v in refreshed.metadata.items() if v})
        refreshed.metadata = merged
        return refreshed

    def revoke(self, credentials: OAuthCredentials) -> None:
        if not self.is_configured():
            return
        try:
            with build_client() as client:
                request(
                    client,
                    "POST",
                    f"{self.api_base}/v2/oauth/revoke/",
                    stage="tiktok.oauth.revoke",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "client_key": settings.tiktok_client_key,
                        "client_secret": settings.tiktok_client_secret,
                        "token": credentials.access_token,
                    },
                    error_parser=self._parse_error,
                )
        except ProviderError as exc:
            logger.warning("tiktok: no se pudo revocar el token: %s", exc)

    # ------------------------------------------------------------- cuenta
    def get_account(self, credentials: OAuthCredentials) -> AccountInfo:
        """Usa `creator_info/query` (no requiere scopes extra de perfil)."""
        info = self.get_creator_info(credentials)
        open_id = str(credentials.metadata.get("open_id") or info.get("creator_username") or "")
        if not open_id:
            raise PermanentProviderError("TikTok no devolvió el identificador de la cuenta")
        return AccountInfo(
            external_account_id=open_id,
            account_name=str(
                info.get("creator_username") or info.get("creator_nickname") or open_id
            ),
            metadata={
                "open_id": credentials.metadata.get("open_id"),
                "creator_nickname": info.get("creator_nickname"),
                "creator_avatar_url": info.get("creator_avatar_url"),
                "privacy_level_options": info.get("privacy_level_options", []),
                "max_video_post_duration_sec": info.get("max_video_post_duration_sec"),
                "audit_passed": settings.tiktok_audit_passed,
                "post_mode": settings.tiktok_post_mode,
            },
        )

    def get_creator_info(self, credentials: OAuthCredentials) -> dict[str, Any]:
        """`POST /v2/post/publish/creator_info/query/` — obligatorio antes de publicar.

        Devuelve las opciones de privacidad permitidas, si el creador tiene
        duet/stitch/comentarios desactivados y la duración máxima permitida.
        """
        self._require_config()
        with build_client() as client:
            return self._api_post(
                client,
                "/v2/post/publish/creator_info/query/",
                stage="tiktok.creator_info",
                token=credentials.access_token,
            )

    # -------------------------------------------------------- chunk sizing
    @staticmethod
    def compute_chunks(size_bytes: int) -> tuple[int, int]:
        """Devuelve `(chunk_size, total_chunk_count)` según las reglas de TikTok.

        - Ficheros < 64 MB: una sola petición (chunk_size = tamaño total).
        - Ficheros >= 64 MB: chunks de 64 MB; el último chunk absorbe el resto
          (TikTok permite que el último chunk sea mayor que `chunk_size`).
        """
        if size_bytes <= 0:
            raise InvalidVideoError("El video está vacío")
        if size_bytes < WHOLE_FILE_LIMIT:
            return size_bytes, 1

        chunk_size = MAX_CHUNK_SIZE
        total = size_bytes // chunk_size
        if total > MAX_CHUNK_COUNT:
            chunk_size = math.ceil(size_bytes / MAX_CHUNK_COUNT)
            if chunk_size > MAX_CHUNK_SIZE:
                raise InvalidVideoError(
                    f"El video es demasiado grande para TikTok ({size_bytes} bytes)"
                )
            total = size_bytes // chunk_size
        return chunk_size, max(total, 1)

    # ------------------------------------------------------------- publish
    def _build_post_info(
        self, request_data: PublishRequest, creator_info: dict[str, Any]
    ) -> dict[str, Any]:
        options = request_data.options
        title = (request_data.caption or request_data.title or "")[:2200]

        allowed = creator_info.get("privacy_level_options") or []
        requested = options.get("privacy_level")
        if not requested:
            # Sin audit aprobado TikTok fuerza privado: pedimos SELF_ONLY para
            # que el resultado sea coherente con lo que la plataforma permite.
            requested = "PUBLIC_TO_EVERYONE" if settings.tiktok_audit_passed else "SELF_ONLY"
        if allowed and requested not in allowed:
            raise PermanentProviderError(
                f"privacy_level '{requested}' no está permitido para este creador. "
                f"Opciones válidas: {', '.join(allowed)}",
                stage="tiktok.post_info",
            )

        post_info: dict[str, Any] = {
            "title": title,
            "privacy_level": requested,
            "disable_duet": bool(
                options.get("disable_duet", creator_info.get("duet_disabled", False))
            ),
            "disable_comment": bool(
                options.get("disable_comment", creator_info.get("comment_disabled", False))
            ),
            "disable_stitch": bool(
                options.get("disable_stitch", creator_info.get("stitch_disabled", False))
            ),
        }
        if options.get("video_cover_timestamp_ms") is not None:
            post_info["video_cover_timestamp_ms"] = int(options["video_cover_timestamp_ms"])
        if options.get("brand_content_toggle") is not None:
            post_info["brand_content_toggle"] = bool(options["brand_content_toggle"])
        if options.get("brand_organic_toggle") is not None:
            post_info["brand_organic_toggle"] = bool(options["brand_organic_toggle"])
        if options.get("is_aigc") is not None:
            post_info["is_aigc"] = bool(options["is_aigc"])
        return post_info

    def init_upload(
        self,
        credentials: OAuthCredentials,
        request_data: PublishRequest,
        *,
        direct_post: bool,
        creator_info: dict[str, Any],
    ) -> tuple[str, str | None]:
        """Inicializa la publicación. Devuelve `(publish_id, upload_url | None)`."""
        video = request_data.video
        if video.public_url:
            source_info: dict[str, Any] = {
                "source": "PULL_FROM_URL",
                "video_url": video.public_url,
            }
        else:
            chunk_size, total = self.compute_chunks(video.size_bytes)
            source_info = {
                "source": "FILE_UPLOAD",
                "video_size": video.size_bytes,
                "chunk_size": chunk_size,
                "total_chunk_count": total,
            }

        payload: dict[str, Any] = {"source_info": source_info}
        path = "/v2/post/publish/inbox/video/init/"
        if direct_post:
            payload["post_info"] = self._build_post_info(request_data, creator_info)
            path = "/v2/post/publish/video/init/"

        with build_client() as client:
            data = self._api_post(
                client,
                path,
                stage="tiktok.init_upload",
                token=credentials.access_token,
                json_payload=payload,
            )
        publish_id = data.get("publish_id")
        if not publish_id:
            raise PermanentProviderError(
                "TikTok no devolvió publish_id", stage="tiktok.init_upload"
            )
        return str(publish_id), data.get("upload_url")

    def upload_video(
        self, upload_url: str, request_data: PublishRequest, *, chunk_size: int
    ) -> None:
        """Sube el video por chunks con `Content-Range` (PUT a `upload_url`)."""
        video = request_data.video
        total_size = video.size_bytes
        content_type = video.content_type or "video/mp4"

        with build_client(timeout=settings.upload_timeout_seconds) as client:
            for offset, chunk in self._iter_chunks(video, chunk_size, total_size):
                last = offset + len(chunk) - 1
                request(
                    client,
                    "PUT",
                    upload_url,
                    stage="tiktok.upload_video",
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{last}/{total_size}",
                    },
                    content=chunk,
                    error_parser=self._parse_error,
                )
                logger.info("tiktok: chunk subido bytes=%s-%s/%s", offset, last, total_size)

    @staticmethod
    def _iter_chunks(video: Any, chunk_size: int, total_size: int):
        """Genera `(offset, bytes)`; el último chunk absorbe el resto del fichero."""
        if video.local_path:
            handle = Path(video.local_path).open("rb")  # noqa: SIM115 - se cierra abajo
            try:
                offset = 0
                while offset < total_size:
                    remaining = total_size - offset
                    # Si lo que queda es menos de 2 chunks, mandamos todo junto.
                    read_size = remaining if remaining < 2 * chunk_size else chunk_size
                    data = handle.read(read_size)
                    if not data:
                        break
                    yield offset, data
                    offset += len(data)
            finally:
                handle.close()
            return

        if not video.open_stream:
            raise ConfigurationError("El video no tiene contenido accesible")
        buffer = bytearray()
        offset = 0
        for piece in video.open_stream():
            buffer.extend(piece)
            while len(buffer) >= chunk_size and (total_size - offset) >= 2 * chunk_size:
                data = bytes(buffer[:chunk_size])
                del buffer[:chunk_size]
                yield offset, data
                offset += len(data)
        if buffer:
            yield offset, bytes(buffer)

    def check_status(self, credentials: OAuthCredentials, publish_id: str) -> RemoteStatus:
        """`POST /v2/post/publish/status/fetch/`.

        `status` ∈ {PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, SEND_TO_USER_INBOX,
        PUBLISH_COMPLETE, FAILED}.
        """
        with build_client() as client:
            data = self._api_post(
                client,
                "/v2/post/publish/status/fetch/",
                stage="tiktok.check_status",
                token=credentials.access_token,
                json_payload={"publish_id": publish_id},
            )
        status = str(data.get("status") or "PROCESSING_UPLOAD").upper()
        return RemoteStatus(
            state=status,
            is_final=status in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"},
            raw=data,
        )

    def wait_for_publish(
        self, credentials: OAuthCredentials, publish_id: str, *, direct_post: bool
    ) -> dict[str, Any]:
        """Polling controlado hasta estado final."""
        last = "PROCESSING_UPLOAD"
        for _tick in poll_ticks(
            timeout_seconds=settings.processing_timeout_seconds,
            interval_seconds=settings.processing_poll_interval_seconds,
        ):
            status = self.check_status(credentials, publish_id)
            last = status.state
            if status.state == "PUBLISH_COMPLETE":
                return status.raw
            if status.state == "SEND_TO_USER_INBOX":
                if direct_post:
                    # No debería pasar en DIRECT_POST, pero es un estado final.
                    return status.raw
                return status.raw
            if status.state == "FAILED":
                reason = status.raw.get("fail_reason") or "sin detalle"
                if reason in _VIDEO_CODES:
                    raise InvalidVideoError(
                        f"TikTok rechazó el video: {reason}",
                        stage="tiktok.processing",
                        platform_code=str(reason),
                        details=status.raw,
                    )
                raise PermanentProviderError(
                    f"TikTok falló al publicar: {reason}",
                    stage="tiktok.processing",
                    platform_code=str(reason),
                    details=status.raw,
                )
        raise ProcessingTimeoutError(
            f"TikTok sigue procesando tras {settings.processing_timeout_seconds}s "
            f"(último estado: {last})",
            stage="tiktok.processing",
        )

    def publish(self, credentials: OAuthCredentials, request_data: PublishRequest) -> PublishResult:
        """Orquesta creator_info → init → upload → status. Reanudable."""
        self._require_config()
        mode = str(request_data.options.get("post_mode") or settings.tiktok_post_mode).upper()
        direct_post = mode == "DIRECT_POST"

        publish_id = request_data.state.get("publish_id")
        if not publish_id:
            request_data.set_stage("uploading")
            creator_info = self.get_creator_info(credentials) if direct_post else {}
            self._validate_duration(request_data, creator_info)

            publish_id, upload_url = self.init_upload(
                credentials, request_data, direct_post=direct_post, creator_info=creator_info
            )
            request_data.save_state(
                publish_id=publish_id, upload_url=upload_url, direct_post=direct_post
            )

            if upload_url:
                chunk_size, _ = self.compute_chunks(request_data.video.size_bytes)
                self.upload_video(upload_url, request_data, chunk_size=chunk_size)
                request_data.save_state(uploaded=True)

        request_data.set_stage("processing")
        raw = self.wait_for_publish(credentials, str(publish_id), direct_post=direct_post)

        post_ids = raw.get("publicaly_available_post_id") or raw.get("publicly_available_post_id")
        external_id = (
            str(post_ids[0]) if isinstance(post_ids, list) and post_ids else str(publish_id)
        )
        username = credentials.metadata.get("creator_username") or credentials.metadata.get(
            "username"
        )
        external_url = (
            f"https://www.tiktok.com/@{username}/video/{external_id}"
            if username and post_ids
            else None
        )
        return PublishResult(
            external_post_id=external_id,
            external_url=external_url,
            metadata={
                "publish_id": publish_id,
                "status": raw.get("status"),
                "post_mode": mode,
                "audit_passed": settings.tiktok_audit_passed,
                "note": (
                    None
                    if settings.tiktok_audit_passed
                    else "La app de TikTok no ha pasado el audit: el contenido "
                    "queda restringido a visibilidad privada."
                ),
            },
        )

    @staticmethod
    def _validate_duration(request_data: PublishRequest, creator_info: dict[str, Any]) -> None:
        """Comprueba la duración contra el máximo que permite el creador."""
        max_duration = creator_info.get("max_video_post_duration_sec")
        declared = request_data.options.get("duration_seconds")
        if max_duration and declared and float(declared) > float(max_duration):
            raise InvalidVideoError(
                f"El video dura {declared}s y TikTok permite hasta {max_duration}s "
                "para esta cuenta",
                stage="tiktok.validate",
            )

    def get_post_status(self, credentials: OAuthCredentials, external_post_id: str) -> RemoteStatus:
        """TikTok sólo expone estado por `publish_id`, no por post id."""
        return self.check_status(credentials, external_post_id)
