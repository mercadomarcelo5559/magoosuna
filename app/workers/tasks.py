"""Tareas Celery: publicación, reintentos, refresco de tokens y limpieza."""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.database import session_scope
from app.logging_config import get_logger
from app.models import (
    OAuthState,
    Platform,
    Post,
    PostStatus,
    ScheduledPost,
    ScheduleStatus,
    SocialAccount,
    utcnow,
)
from app.providers.errors import AuthenticationError, ProviderError
from app.services import accounts as accounts_service
from app.services import media as media_service
from app.services import posts as posts_service
from app.services import publisher
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

WORKER_ID = socket.gethostname()


@celery_app.task(name="app.workers.tasks.publish_post", bind=True, max_retries=0)
def publish_post_task(self, post_id: str) -> dict[str, Any]:  # noqa: ARG001
    """Publica un post. Los reintentos los gestiona `publisher` + el barredor.

    No usamos `self.retry` para que la política de reintentos viva en la base
    de datos: así el trabajo sobrevive al reinicio del worker (Codespaces).
    """
    with session_scope() as db:
        post = db.get(Post, post_id)
        if post is None:
            logger.warning("tasks: post %s no existe", post_id)
            return {"post_id": post_id, "status": "not_found"}
        outcome = publisher.publish_post(db, post)
        return outcome.to_dict()


@celery_app.task(name="app.workers.tasks.publish_group")
def publish_group_task(group_id: str) -> list[dict[str, Any]]:
    """Encola cada post del grupo por separado (aislamiento entre plataformas)."""
    with session_scope() as db:
        posts = list(db.scalars(select(Post).where(Post.group_id == group_id)))
    results: list[dict[str, Any]] = []
    for post in posts:
        if PostStatus(post.status) in {PostStatus.QUEUED, PostStatus.DRAFT}:
            results.append({"post_id": post.id, "queued": True})
            publish_post_task.delay(post.id)
    return results


@celery_app.task(name="app.workers.tasks.sweep_scheduled_posts")
def sweep_scheduled_posts() -> dict[str, int]:
    """Despacha las publicaciones programadas cuya hora ya llegó.

    Lee de la tabla `scheduled_posts`, que es la fuente de verdad: si el worker
    estuvo apagado, al arrancar recupera todo lo vencido.
    """
    dispatched = 0
    with session_scope() as db:
        schedules: list[ScheduledPost] = posts_service.due_schedules(db, limit=100)
        for schedule in schedules:
            post = db.get(Post, schedule.post_id)
            if post is None:
                schedule.status = ScheduleStatus.CANCELLED
                db.add(schedule)
                continue
            if PostStatus(post.status).is_terminal:
                posts_service.mark_schedule_dispatched(db, schedule, WORKER_ID)
                continue
            if PostStatus(post.status) == PostStatus.SCHEDULED:
                post.status = PostStatus.QUEUED
                db.add(post)
            posts_service.mark_schedule_dispatched(db, schedule, WORKER_ID)
            publish_post_task.delay(post.id)
            dispatched += 1
    if dispatched:
        logger.info("tasks: %s publicaciones programadas despachadas", dispatched)
    return {"dispatched": dispatched}


@celery_app.task(name="app.workers.tasks.retry_pending_posts")
def retry_pending_posts() -> dict[str, int]:
    """Relanza los posts en `queued` cuyo backoff ya venció."""
    dispatched = 0
    with session_scope() as db:
        for post in posts_service.pending_posts_for_dispatch(db, limit=50):
            publish_post_task.delay(post.id)
            dispatched += 1
    if dispatched:
        logger.info("tasks: %s posts reencolados", dispatched)
    return {"dispatched": dispatched}


@celery_app.task(name="app.workers.tasks.sync_stuck_posts")
def sync_stuck_posts() -> dict[str, int]:
    """Consulta la plataforma para posts atascados en `processing`.

    Esto es el *polling controlado* del punto 16: sólo para posts realmente
    atascados (más de 30 min) y con un límite por ejecución.
    """
    synced = 0
    with session_scope() as db:
        for post in posts_service.stuck_posts(db, older_than_minutes=30, limit=20):
            publisher.sync_post_status(db, post)
            synced += 1
    return {"synced": synced}


@celery_app.task(name="app.workers.tasks.refresh_expiring_tokens")
def refresh_expiring_tokens() -> dict[str, int]:
    """Renueva proactivamente los tokens que caducan en las próximas 48 h."""
    refreshed = 0
    failed = 0
    threshold = utcnow() + timedelta(hours=48)
    with session_scope() as db:
        accounts = list(
            db.scalars(
                select(SocialAccount).where(
                    SocialAccount.is_active.is_(True),
                    SocialAccount.token_expiration.is_not(None),
                    SocialAccount.token_expiration <= threshold,
                )
            )
        )
        for account in accounts:
            try:
                accounts_service.ensure_fresh_credentials(db, account, force=True)
                refreshed += 1
            except AuthenticationError:
                failed += 1
                logger.warning(
                    "tasks: cuenta %s (%s) requiere reconexión manual",
                    account.id,
                    account.platform,
                )
            except ProviderError as exc:
                failed += 1
                logger.warning("tasks: refresco fallido para %s: %s", account.id, exc)
    if refreshed or failed:
        logger.info("tasks: tokens renovados=%s fallidos=%s", refreshed, failed)
    return {"refreshed": refreshed, "failed": failed}


@celery_app.task(name="app.workers.tasks.purge_expired_media")
def purge_expired_media() -> dict[str, int]:
    """Borra los videos caducados que ya no hacen falta."""
    with session_scope() as db:
        deleted = media_service.purge_expired_assets(db, limit=200)
    return {"deleted": deleted}


@celery_app.task(name="app.workers.tasks.purge_oauth_states")
def purge_oauth_states() -> dict[str, int]:
    """Elimina los `state` de OAuth caducados."""
    with session_scope() as db:
        stale = list(
            db.scalars(select(OAuthState).where(OAuthState.expires_at <= utcnow()).limit(500))
        )
        for state in stale:
            db.delete(state)
    return {"deleted": len(stale)}


@celery_app.task(name="app.workers.tasks.sync_post")
def sync_post_task(post_id: str) -> dict[str, Any]:
    """Sincroniza el estado de un post concreto con la plataforma."""
    with session_scope() as db:
        post = db.get(Post, post_id)
        if post is None:
            return {"post_id": post_id, "status": "not_found"}
        publisher.sync_post_status(db, post)
        return {"post_id": post_id, "status": str(post.status)}


def enqueue_post(post_id: str, *, countdown: float | None = None) -> str | None:
    """Encola la publicación de un post. Devuelve el id de tarea si aplica."""
    result = publish_post_task.apply_async(args=[post_id], countdown=countdown or None)
    return getattr(result, "id", None)


def enqueue_platform_refresh(platform: Platform) -> None:  # pragma: no cover
    """Hook de extensión: refresco por plataforma si algún día hace falta."""
    logger.debug("enqueue_platform_refresh(%s) no requiere acción", platform)
