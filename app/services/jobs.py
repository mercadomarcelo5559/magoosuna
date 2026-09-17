"""Trabajos periódicos, independientes del modo de ejecución.

Los ejecutan tanto el planificador embebido (`app.services.scheduler`) como
las tareas de Celery (`app.workers.tasks`). Escribir la lógica una sola vez
evita que los dos caminos se desincronicen.
"""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.database import session_scope
from app.logging_config import get_logger
from app.models import (
    OAuthState,
    Post,
    PostStatus,
    ScheduleStatus,
    SocialAccount,
    utcnow,
)
from app.providers.errors import AuthenticationError, ProviderError
from app.services import accounts as accounts_service
from app.services import dispatch, publisher
from app.services import media as media_service
from app.services import posts as posts_service

logger = get_logger(__name__)

WORKER_ID = socket.gethostname()


def sweep_scheduled_posts() -> dict[str, int]:
    """Despacha las publicaciones programadas cuya hora ya llegó.

    Lee de `scheduled_posts`, que es la fuente de verdad: si el servicio
    estuvo parado, al arrancar recupera todo lo vencido.
    """
    despachadas = 0
    pendientes: list[str] = []
    with session_scope() as db:
        for schedule in posts_service.due_schedules(db, limit=100):
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
                db.commit()
            posts_service.mark_schedule_dispatched(db, schedule, WORKER_ID)
            pendientes.append(post.id)
            despachadas += 1

    for post_id in pendientes:
        dispatch.enqueue_post(post_id)

    if despachadas:
        logger.info("jobs: %s publicaciones programadas despachadas", despachadas)
    return {"dispatched": despachadas}


def retry_pending_posts() -> dict[str, int]:
    """Relanza los posts en `queued` cuyo backoff ya venció."""
    with session_scope() as db:
        pendientes = [p.id for p in posts_service.pending_posts_for_dispatch(db, limit=50)]

    for post_id in pendientes:
        dispatch.enqueue_post(post_id)

    if pendientes:
        logger.info("jobs: %s posts reencolados", len(pendientes))
    return {"dispatched": len(pendientes)}


def sync_stuck_posts() -> dict[str, int]:
    """Consulta a la plataforma por los posts atascados en `processing`.

    Es el *polling controlado*: sólo posts con más de 30 minutos parados y
    como máximo 20 por ejecución.
    """
    sincronizados = 0
    with session_scope() as db:
        for post in posts_service.stuck_posts(db, older_than_minutes=30, limit=20):
            publisher.sync_post_status(db, post)
            sincronizados += 1
    return {"synced": sincronizados}


def refresh_expiring_tokens() -> dict[str, int]:
    """Renueva los tokens que caducan en las próximas 48 h."""
    renovados = 0
    fallidos = 0
    limite = utcnow() + timedelta(hours=48)
    with session_scope() as db:
        cuentas = list(
            db.scalars(
                select(SocialAccount).where(
                    SocialAccount.is_active.is_(True),
                    SocialAccount.token_expiration.is_not(None),
                    SocialAccount.token_expiration <= limite,
                )
            )
        )
        for cuenta in cuentas:
            try:
                accounts_service.ensure_fresh_credentials(db, cuenta, force=True)
                renovados += 1
            except AuthenticationError:
                fallidos += 1
                logger.warning(
                    "jobs: la cuenta %s (%s) requiere reconexión manual",
                    cuenta.id,
                    cuenta.platform,
                )
            except ProviderError as exc:
                fallidos += 1
                logger.warning("jobs: refresco fallido para %s: %s", cuenta.id, exc)
    if renovados or fallidos:
        logger.info("jobs: tokens renovados=%s fallidos=%s", renovados, fallidos)
    return {"refreshed": renovados, "failed": fallidos}


def purge_expired_media() -> dict[str, int]:
    """Borra los videos caducados que ya no hacen falta."""
    with session_scope() as db:
        borrados = media_service.purge_expired_assets(db, limit=200)
    return {"deleted": borrados}


def purge_oauth_states() -> dict[str, int]:
    """Elimina los `state` de OAuth caducados."""
    with session_scope() as db:
        caducados = list(
            db.scalars(select(OAuthState).where(OAuthState.expires_at <= utcnow()).limit(500))
        )
        for estado in caducados:
            db.delete(estado)
        total = len(caducados)
    return {"deleted": total}


def recover_interrupted_posts() -> dict[str, int]:
    """Devuelve a la cola los posts que quedaron a medias al pararse el servicio.

    Si el proceso murió mientras publicaba, el post se quedó en `uploading`.
    Al arrancar se reencolan: el provider reanuda desde el estado guardado
    (container_id, publish_id o session_url), así que no se re-sube el video.
    """
    recuperados: list[str] = []
    with session_scope() as db:
        atascados = list(
            db.scalars(
                select(Post)
                .where(Post.status == PostStatus.UPLOADING)
                .order_by(Post.updated_at)
                .limit(50)
            )
        )
        for post in atascados:
            post.status = PostStatus.QUEUED
            db.add(post)
            recuperados.append(post.id)
        db.commit()

    for post_id in recuperados:
        dispatch.enqueue_post(post_id)

    if recuperados:
        logger.info("jobs: %s publicaciones interrumpidas devueltas a la cola", len(recuperados))
    return {"recovered": len(recuperados)}


def sync_post(post_id: str) -> dict[str, Any]:
    """Sincroniza el estado de un post concreto con su plataforma."""
    with session_scope() as db:
        post = db.get(Post, post_id)
        if post is None:
            return {"post_id": post_id, "status": "not_found"}
        publisher.sync_post_status(db, post)
        return {"post_id": post_id, "status": str(post.status)}
