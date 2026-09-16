"""Enumeraciones del dominio."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    # Preparado para crecer sin cambiar el modelo de datos:
    FACEBOOK = "facebook"
    X = "x"
    LINKEDIN = "linkedin"


class PostStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {PostStatus.PUBLISHED, PostStatus.FAILED, PostStatus.CANCELLED}

    @property
    def is_active(self) -> bool:
        return self in {
            PostStatus.QUEUED,
            PostStatus.UPLOADING,
            PostStatus.PROCESSING,
            PostStatus.PUBLISHING,
        }


class AttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"


class ErrorCategory(StrEnum):
    """Clasificación usada para decidir si se reintenta y con qué espera."""

    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    PERMANENT = "permanent"
    CONFIGURATION = "configuration"
    INVALID_VIDEO = "invalid_video"
    PROCESSING_TIMEOUT = "processing_timeout"
    INTERNAL = "internal"

    @property
    def retryable(self) -> bool:
        return self in {
            ErrorCategory.TRANSIENT,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.PROCESSING_TIMEOUT,
            ErrorCategory.INTERNAL,
        }


class MediaStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DELETED = "deleted"
    FAILED = "failed"


class MediaSource(StrEnum):
    UPLOAD = "upload"
    URL = "url"


class ScheduleStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    CANCELLED = "cancelled"
