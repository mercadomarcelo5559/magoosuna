"""Configuración central de la aplicación.

Todos los valores se leen de variables de entorno (ver `.env.example`).
Nunca se escriben secretos en el código.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Social Video API"
    environment: Environment = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = False

    #: URL pública HTTPS de esta API. Necesaria para callbacks OAuth y para
    #: entregar los videos a Instagram/TikTok mediante `video_url`.
    #: En Codespaces: https://<codespace>-8000.app.github.dev
    public_base_url: str = "http://localhost:8000"

    api_prefix: str = "/v1"

    # ----------------------------------------------------------- seguridad
    #: Clave maestra Fernet (urlsafe base64, 32 bytes) para cifrar tokens OAuth.
    #: Generar con: python -m app.security.crypto --generate-key
    encryption_key: str = ""

    #: Clave HMAC para firmar URLs temporales de descarga de media y states OAuth.
    signing_secret: str = ""

    #: API keys de administración (crea/rota otras API keys). Coma-separadas.
    admin_api_keys: str = ""

    #: API keys de clientes para bootstrap en desarrollo. Coma-separadas.
    #: En producción se crean vía POST /v1/admin/clients.
    bootstrap_api_keys: str = ""

    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = False

    # ------------------------------------------------------------ database
    database_url: str = "sqlite:///./data/social_video_api.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --------------------------------------------------------------- redis
    redis_url: str = "redis://localhost:6379/0"

    # ------------------------------------------------- modo de publicación
    #: Cómo se ejecutan las publicaciones:
    #:   "solo"   → en hilos del propio proceso de la API. Un solo servicio,
    #:              sin Redis ni worker aparte. Recomendado para un VPS.
    #:   "celery" → worker Celery externo con Redis. Para escalar.
    #:   "inline" → síncrono dentro de la petición (tests y depuración).
    publish_mode: Literal["solo", "celery", "inline"] = "solo"
    #: Publicaciones simultáneas en modo "solo". Una máquina pequeña aguanta 2-4.
    publish_concurrency: int = 3

    # -------------------------------------------------------------- celery
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    #: Compatibilidad: equivale a PUBLISH_MODE=inline.
    celery_task_always_eager: bool = False

    #: Ejecuta el barredor de publicaciones programadas dentro del proceso API.
    #: Cómodo en Codespaces; en producción usar `celery beat`.
    scheduler_in_process: bool = True
    scheduler_interval_seconds: int = 30

    # ------------------------------------------------------------- storage
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./data/media"
    #: Horas que se conserva un video subido antes de borrarse.
    media_retention_hours: int = 24
    #: Minutos de validez de una URL de descarga firmada.
    media_url_ttl_minutes: int = 120

    s3_bucket: str = ""
    s3_region: str = "auto"
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"

    # ------------------------------------------------------- validación video
    max_video_size_mb: int = 512
    allowed_video_mime_types: str = "video/mp4,video/quicktime,video/webm"
    allowed_video_extensions: str = ".mp4,.mov,.webm"
    #: Tamaño de bloque al leer/streamear video (bytes).
    stream_chunk_size: int = 1024 * 1024

    # -------------------------------------------------------- rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    # ------------------------------------------------------------- retries
    max_publish_attempts: int = 5
    retry_base_delay_seconds: int = 30
    retry_max_delay_seconds: int = 3600

    #: Tiempo máximo esperando que una plataforma procese el video (segundos).
    processing_timeout_seconds: int = 900
    #: Intervalo entre consultas de estado (segundos). No hacer polling agresivo.
    processing_poll_interval_seconds: int = 20

    http_timeout_seconds: float = 60.0
    upload_timeout_seconds: float = 600.0

    # ----------------------------------------------------------- Instagram
    #: "instagram" = Business Login for Instagram (graph.instagram.com)
    #: "facebook"  = Facebook Login for Business (graph.facebook.com)
    instagram_login_mode: Literal["instagram", "facebook"] = "instagram"
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = ""
    instagram_graph_version: str = "v25.0"
    instagram_graph_base: str = "https://graph.instagram.com"
    instagram_facebook_graph_base: str = "https://graph.facebook.com"
    instagram_rupload_base: str = "https://rupload.facebook.com/ig-api-upload"
    instagram_scopes: str = "instagram_business_basic,instagram_business_content_publish"
    instagram_facebook_scopes: str = (
        "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"
    )

    # -------------------------------------------------------------- TikTok
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""
    tiktok_scopes: str = "user.info.basic,video.publish,video.upload"
    #: DIRECT_POST publica directamente; INBOX deja el video en el borrador
    #: del usuario dentro de la app de TikTok (no requiere audit para publicar).
    tiktok_post_mode: Literal["DIRECT_POST", "INBOX"] = "DIRECT_POST"
    #: True cuando la app ya pasó el audit de TikTok. Si es False la API avisa
    #: que el contenido quedará en modo privado (SELF_ONLY).
    tiktok_audit_passed: bool = False
    tiktok_api_base: str = "https://open.tiktokapis.com"
    tiktok_auth_base: str = "https://www.tiktok.com"

    # ------------------------------------------------------------- YouTube
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = ""
    youtube_scopes: str = (
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.readonly"
    )
    youtube_default_privacy: Literal["private", "unlisted", "public"] = "private"
    youtube_default_category_id: str = "22"
    youtube_api_base: str = "https://www.googleapis.com/youtube/v3"
    youtube_upload_base: str = "https://www.googleapis.com/upload/youtube/v3"
    youtube_oauth_auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    youtube_oauth_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105 - es una URL

    # ------------------------------------------------------------- helpers
    @model_validator(mode="after")
    def _compatibilidad_eager(self) -> Settings:
        """`CELERY_TASK_ALWAYS_EAGER=true` sigue significando modo inline.

        Sólo se aplica si NO se indicó `PUBLISH_MODE` explícitamente: un modo
        puesto a mano siempre manda sobre la variable antigua.
        """
        if self.celery_task_always_eager and "publish_mode" not in self.model_fields_set:
            object.__setattr__(self, "publish_mode", "inline")
        return self

    @field_validator("public_base_url", "s3_public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return self._csv(self.cors_allow_origins)

    @property
    def admin_api_key_list(self) -> list[str]:
        return self._csv(self.admin_api_keys)

    @property
    def bootstrap_api_key_list(self) -> list[str]:
        return self._csv(self.bootstrap_api_keys)

    @property
    def allowed_mime_types(self) -> set[str]:
        return {m.lower() for m in self._csv(self.allowed_video_mime_types)}

    @property
    def allowed_extensions(self) -> set[str]:
        return {
            e.lower() if e.startswith(".") else f".{e.lower()}"
            for e in self._csv(self.allowed_video_extensions)
        }

    @property
    def max_video_size_bytes(self) -> int:
        return self.max_video_size_mb * 1024 * 1024

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def uses_celery(self) -> bool:
        return self.publish_mode == "celery"

    @property
    def needs_redis(self) -> bool:
        """Redis sólo es imprescindible con Celery; si no, es opcional."""
        return self.uses_celery

    @property
    def instagram_scope_list(self) -> list[str]:
        raw = (
            self.instagram_scopes
            if self.instagram_login_mode == "instagram"
            else self.instagram_facebook_scopes
        )
        return self._csv(raw)

    @property
    def tiktok_scope_list(self) -> list[str]:
        return self._csv(self.tiktok_scopes)

    @property
    def youtube_scope_list(self) -> list[str]:
        return [s for s in self.youtube_scopes.replace(",", " ").split() if s]


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
