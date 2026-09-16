"""Schemas de publicaciones."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AttemptStatus, ErrorCategory, Platform, PostStatus


class CreatePostRequest(BaseModel):
    """Cuerpo de `POST /v1/posts`.

    El video se indica de una de estas tres formas (exactamente una):
      * `media_id`  — un video ya subido a `POST /v1/media`
      * `video_url` — URL pública que la API descargará y validará
      * multipart   — usa `POST /v1/posts/upload` para enviar el fichero
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "media_id": "8f2b1c4e-...",
                "caption": "Nuevo reel 🔥 #magoosuna",
                "title": "Mi video",
                "description": "Descripción larga para YouTube",
                "tags": ["magoosuna", "reels"],
                "platforms": ["instagram", "tiktok", "youtube"],
                "scheduled_at": None,
                "platform_options": {
                    "youtube": {"privacy_status": "public"},
                    "tiktok": {"privacy_level": "PUBLIC_TO_EVERYONE"},
                },
            }
        }
    )

    media_id: str | None = Field(default=None, description="Id devuelto por POST /v1/media")
    video_url: str | None = Field(default=None, description="URL pública del video")
    platforms: list[Platform] = Field(
        min_length=1, description="Plataformas destino: instagram, tiktok, youtube"
    )
    caption: str | None = Field(default=None, max_length=5000)
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    scheduled_at: datetime | None = Field(
        default=None,
        description="Fecha/hora futura en ISO-8601 (UTC o con offset). Null = publicar ya",
    )
    platform_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Opciones por plataforma, p. ej. {'youtube': {'privacy_status': 'public'}}",
    )
    account_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Cuenta concreta por plataforma; por defecto la más reciente",
    )

    @field_validator("platforms")
    @classmethod
    def _dedupe_platforms(cls, value: list[Platform]) -> list[Platform]:
        seen: list[Platform] = []
        for platform in value:
            if platform not in seen:
                seen.append(platform)
        return seen

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        return [tag.strip().lstrip("#") for tag in value if tag and tag.strip()]

    @field_validator("platform_options", "account_ids")
    @classmethod
    def _validate_platform_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            try:
                Platform(key)
            except ValueError as exc:
                raise ValueError(f"Plataforma desconocida en las opciones: '{key}'") from exc
        return value

    @model_validator(mode="after")
    def _require_one_source(self) -> CreatePostRequest:
        if bool(self.media_id) == bool(self.video_url):
            raise ValueError(
                "Indica exactamente uno de `media_id` o `video_url` "
                "(o usa POST /v1/posts/upload para enviar el fichero)"
            )
        return self


class PostAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    status: AttemptStatus
    stage: str | None = None
    error_category: ErrorCategory | None = None
    error_message: str | None = None
    http_status: int | None = None
    duration_ms: int | None = None
    started_at: datetime
    finished_at: datetime | None = None


class PostResponse(BaseModel):
    """Publicación en una plataforma concreta."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: Platform
    status: PostStatus
    social_account_id: str
    external_post_id: str | None = None
    external_url: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    error_message: str | None = None
    error_category: ErrorCategory | None = None
    attempt_count: int
    next_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    attempts: list[PostAttemptResponse] = Field(default_factory=list)


class PostGroupResponse(BaseModel):
    """Resultado de `POST /v1/posts` y de `GET /v1/posts/{id}`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PostStatus = Field(description="Estado agregado de todas las plataformas")
    media_id: str
    caption: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    posts: list[PostResponse] = Field(default_factory=list)
    skipped_platforms: dict[str, str] = Field(
        default_factory=dict,
        description="Plataformas solicitadas sin cuenta conectada, con el motivo",
    )

    @classmethod
    def from_group(cls, group: Any) -> PostGroupResponse:
        return cls(
            id=group.id,
            status=group.aggregate_status,
            media_id=group.media_asset_id,
            caption=group.caption,
            title=group.title,
            description=group.description,
            tags=list(group.tags or []),
            scheduled_at=group.scheduled_at,
            created_at=group.created_at,
            updated_at=group.updated_at,
            posts=[PostResponse.model_validate(post) for post in group.posts],
            skipped_platforms=dict((group.options or {}).get("skipped") or {}),
        )


class RetryPostResponse(BaseModel):
    post: PostResponse
    message: str


class CancelPostResponse(BaseModel):
    id: str
    cancelled: list[str] = Field(description="Ids de posts cancelados")
    not_cancelled: dict[str, str] = Field(
        default_factory=dict, description="Posts que no se pudieron cancelar y por qué"
    )
