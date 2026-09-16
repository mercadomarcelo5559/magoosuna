"""Motor de publicación: ejecuta un `Post` contra su provider.

Responsabilidades:
  * refrescar credenciales antes de publicar,
  * registrar cada intento en `post_attempts`,
  * mover el `Post` por los estados del ciclo de vida,
  * clasificar errores y programar reintentos con backoff,
  * guardar ids/URLs externas.

Un fallo en una plataforma NO afecta a las demás: cada `Post` se publica de
forma independiente.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import (
    AttemptStatus,
    ErrorCategory,
    Post,
    PostAttempt,
    PostStatus,
    utcnow,
)
from app.models.base import as_utc
from app.providers import PublishRequest, get_provider
from app.providers.errors import ProviderError
from app.services import accounts as accounts_service
from app.services import media as media_service
from app.services.retry import classify, next_retry_at, retry_after_from, should_retry

logger = get_logger(__name__)

#: Estados desde los que tiene sentido lanzar una publicación.
PUBLISHABLE_STATES = {
    PostStatus.DRAFT,
    PostStatus.QUEUED,
    PostStatus.SCHEDULED,
    PostStatus.UPLOADING,
    PostStatus.PROCESSING,
    PostStatus.PUBLISHING,
}

_STAGE_TO_STATUS = {
    "uploading": PostStatus.UPLOADING,
    "processing": PostStatus.PROCESSING,
    "publishing": PostStatus.PUBLISHING,
}


class PublishOutcome:
    """Resultado de un intento de publicación."""

    def __init__(
        self,
        post_id: str,
        status: PostStatus,
        *,
        external_post_id: str | None = None,
        external_url: str | None = None,
        error_message: str | None = None,
        error_category: ErrorCategory | None = None,
        retry_scheduled: bool = False,
    ) -> None:
        self.post_id = post_id
        self.status = status
        self.external_post_id = external_post_id
        self.external_url = external_url
        self.error_message = error_message
        self.error_category = error_category
        self.retry_scheduled = retry_scheduled

    @property
    def succeeded(self) -> bool:
        return self.status == PostStatus.PUBLISHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "status": str(self.status),
            "external_post_id": self.external_post_id,
            "external_url": self.external_url,
            "error_message": self.error_message,
            "error_category": str(self.error_category) if self.error_category else None,
            "retry_scheduled": self.retry_scheduled,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PublishOutcome {self.post_id} {self.status}>"


def _set_status(db: Session, post: Post, status: PostStatus) -> None:
    post.status = status
    db.add(post)
    db.commit()


def publish_post(db: Session, post: Post) -> PublishOutcome:
    """Publica un `Post`. Nunca lanza: devuelve siempre un `PublishOutcome`."""
    if PostStatus(post.status) in {PostStatus.PUBLISHED, PostStatus.CANCELLED}:
        logger.info("publisher: post %s ya está %s, no se republica", post.id, post.status)
        return PublishOutcome(
            post.id,
            PostStatus(post.status),
            external_post_id=post.external_post_id,
            external_url=post.external_url,
        )

    if PostStatus(post.status) not in PUBLISHABLE_STATES:
        return PublishOutcome(
            post.id,
            PostStatus(post.status),
            error_message=f"El post está en estado {post.status}",
        )

    # `attempt_count` es el presupuesto de reintentos del ciclo actual (se
    # reinicia en `POST /posts/{id}/retry`), mientras que `attempt_number` es
    # una secuencia monótona para auditoría: nunca se repite para un mismo post.
    post.attempt_count += 1
    attempt_number = max((a.attempt_number for a in post.attempts), default=0) + 1
    attempt = PostAttempt(
        post_id=post.id,
        attempt_number=attempt_number,
        status=AttemptStatus.STARTED,
        started_at=utcnow(),
    )
    post.next_retry_at = None
    db.add_all([post, attempt])
    db.commit()

    started = time.monotonic()
    stage_holder = {"stage": "prepare"}

    def on_stage(stage: str) -> None:
        stage_holder["stage"] = stage
        mapped = _STAGE_TO_STATUS.get(stage)
        if mapped:
            _set_status(db, post, mapped)

    def on_state(state: dict[str, Any]) -> None:
        post.provider_state = state
        db.add(post)
        db.commit()

    try:
        provider = get_provider(post.platform)
        account = post.social_account
        if not account.is_active:
            raise ProviderError(
                f"La cuenta de {post.platform} está desconectada; vuelve a conectarla"
            )

        credentials = accounts_service.ensure_fresh_credentials(db, account)
        credentials.metadata.setdefault("external_account_id", account.external_account_id)

        video = media_service.build_video_source(
            post.media_asset, require_public_url=provider.requires_public_url()
        )

        options = dict(post.platform_options or {})
        options.setdefault("ig_user_id", account.external_account_id)

        request = PublishRequest(
            video=video,
            caption=post.caption,
            title=post.title,
            description=post.description,
            tags=list(post.tags or []),
            options=options,
            state=dict(post.provider_state or {}),
            on_state=on_state,
            on_stage=on_stage,
        )

        _set_status(db, post, PostStatus.UPLOADING)
        logger.info(
            "publisher: publicando post_id=%s platform=%s intento=%s",
            post.id,
            post.platform,
            attempt_number,
        )
        result = provider.publish(credentials, request)

        post.external_post_id = result.external_post_id
        post.external_url = result.external_url
        post.status = PostStatus.PUBLISHED
        post.published_at = utcnow()
        post.error_message = None
        post.error_category = None
        post.provider_state = {**(post.provider_state or {}), **result.metadata}

        attempt.status = AttemptStatus.SUCCEEDED
        attempt.stage = "published"
        attempt.finished_at = utcnow()
        attempt.duration_ms = int((time.monotonic() - started) * 1000)
        db.add_all([post, attempt])
        db.commit()

        logger.info(
            "publisher: OK post_id=%s platform=%s external_id=%s url=%s duracion_ms=%s",
            post.id,
            post.platform,
            post.external_post_id,
            post.external_url,
            attempt.duration_ms,
        )
        return PublishOutcome(
            post.id,
            PostStatus.PUBLISHED,
            external_post_id=result.external_post_id,
            external_url=result.external_url,
        )

    except BaseException as exc:
        db.rollback()
        db.refresh(post)
        category = classify(exc)
        message = str(exc)[:2000]
        retry_after = retry_after_from(exc)
        stage = getattr(exc, "stage", None) or stage_holder["stage"]

        attempt = db.get(PostAttempt, attempt.id) or attempt
        attempt.error_category = category
        attempt.error_message = message
        attempt.http_status = getattr(exc, "http_status", None)
        attempt.stage = stage
        attempt.finished_at = utcnow()
        attempt.duration_ms = int((time.monotonic() - started) * 1000)

        retry = should_retry(category, attempt_number)
        post.error_message = message
        post.error_category = category

        if retry:
            post.status = PostStatus.QUEUED
            post.next_retry_at = next_retry_at(category, attempt_number, retry_after=retry_after)
            attempt.status = AttemptStatus.RETRY_SCHEDULED
            logger.warning(
                "publisher: fallo reintentable post_id=%s platform=%s categoria=%s "
                "intento=%s proximo=%s error=%s",
                post.id,
                post.platform,
                category,
                attempt_number,
                post.next_retry_at,
                message,
            )
        else:
            post.status = PostStatus.FAILED
            attempt.status = AttemptStatus.FAILED
            logger.error(
                "publisher: fallo definitivo post_id=%s platform=%s categoria=%s "
                "intento=%s error=%s",
                post.id,
                post.platform,
                category,
                attempt_number,
                message,
            )

        db.add_all([post, attempt])
        db.commit()

        return PublishOutcome(
            post.id,
            PostStatus(post.status),
            error_message=message,
            error_category=category,
            retry_scheduled=retry,
        )


def is_retry_due(post: Post) -> bool:
    """True si el post está esperando un reintento cuya hora ya llegó."""
    if PostStatus(post.status) != PostStatus.QUEUED:
        return False
    retry_at = as_utc(post.next_retry_at)
    return retry_at is None or retry_at <= utcnow()


def retry_delay_seconds(post: Post) -> float:
    """Segundos que faltan para el reintento (0 si ya toca)."""
    retry_at = as_utc(post.next_retry_at)
    if retry_at is None:
        return 0.0
    return max(0.0, (retry_at - utcnow()).total_seconds())


def sync_post_status(db: Session, post: Post) -> Post:
    """Consulta la plataforma para actualizar el estado real del contenido.

    Se usa cuando un post quedó en `processing` (por ejemplo tras un timeout
    de procesado) y queremos saber si la plataforma ya terminó.
    """
    if not post.external_post_id and not (post.provider_state or {}):
        return post
    provider = get_provider(post.platform)
    external_id = post.external_post_id or (post.provider_state or {}).get("publish_id")
    if not external_id:
        return post

    try:
        credentials = accounts_service.ensure_fresh_credentials(db, post.social_account)
        status = provider.get_post_status(credentials, str(external_id))
    except ProviderError as exc:
        logger.warning("publisher: no se pudo sincronizar post %s: %s", post.id, exc)
        return post

    if status.external_url and not post.external_url:
        post.external_url = status.external_url

    finished_states = {"PUBLISHED", "PUBLISH_COMPLETE", "processed", "FINISHED"}
    failed_states = {"FAILED", "failed", "rejected", "ERROR", "EXPIRED"}
    if status.state in finished_states and PostStatus(post.status) != PostStatus.PUBLISHED:
        post.status = PostStatus.PUBLISHED
        post.published_at = post.published_at or utcnow()
        post.error_message = None
    elif status.state in failed_states and not PostStatus(post.status).is_terminal:
        post.status = PostStatus.FAILED
        post.error_message = f"La plataforma reportó estado {status.state}"
        post.error_category = ErrorCategory.PERMANENT

    post.provider_state = {**(post.provider_state or {}), "remote_status": status.state}
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def cancel_post(db: Session, post: Post) -> bool:
    """Cancela un post que aún no se publicó. True si se canceló."""
    current = PostStatus(post.status)
    if current in {PostStatus.PUBLISHED, PostStatus.CANCELLED}:
        return False
    if current in {PostStatus.UPLOADING, PostStatus.PROCESSING, PostStatus.PUBLISHING}:
        # Ya está en manos de la plataforma: no podemos garantizar la cancelación.
        return False

    post.status = PostStatus.CANCELLED
    post.next_retry_at = None
    db.add(post)

    from sqlalchemy import select

    from app.models import ScheduledPost, ScheduleStatus

    schedules = db.scalars(
        select(ScheduledPost).where(
            ScheduledPost.post_id == post.id,
            ScheduledPost.status == ScheduleStatus.PENDING,
        )
    ).all()
    for schedule in schedules:
        schedule.status = ScheduleStatus.CANCELLED
        db.add(schedule)

    db.commit()
    logger.info("publisher: post cancelado post_id=%s", post.id)
    return True


def max_attempts() -> int:
    return settings.max_publish_attempts
