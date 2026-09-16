"""Schemas de media (videos)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import MediaSource, MediaStatus


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: MediaSource
    status: MediaStatus
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None = None
    expires_at: datetime | None = Field(
        default=None, description="Cuándo se borrará el fichero por retención"
    )
    created_at: datetime
    download_url: str | None = Field(
        default=None,
        description=(
            "URL temporal firmada. Es la que se entrega a Instagram/TikTok como "
            "`video_url`; requiere que PUBLIC_BASE_URL sea accesible por Internet."
        ),
    )


class MediaFromUrlRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "video_url": "https://cdn.ejemplo.com/reels/video.mp4",
                "download": True,
            }
        }
    )

    video_url: str = Field(description="URL http(s) pública del video")
    download: bool = Field(
        default=True,
        description=(
            "Si es True la API descarga y valida el fichero (necesario para "
            "YouTube, que no acepta publicar desde URL)."
        ),
    )

    @field_validator("video_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("`video_url` debe empezar por http:// o https://")
        return value.strip()


class MediaLimitsResponse(BaseModel):
    """Límites de subida vigentes, para que Macaly valide antes de enviar."""

    max_size_mb: int
    allowed_mime_types: list[str]
    allowed_extensions: list[str]
    retention_hours: int
    storage_backend: str
    public_url_reachable: bool = Field(
        description=(
            "False si PUBLIC_BASE_URL no es una URL HTTPS pública: en ese caso "
            "Instagram no podrá descargar el video (usa un túnel o S3/R2)."
        )
    )
