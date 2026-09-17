"""Tareas Celery.

Son envoltorios finos sobre `app.services.jobs`: la lógica vive ahí y la
comparten el planificador embebido (modo ``solo``) y estos workers (modo
``celery``), de modo que ambos caminos no pueden desincronizarse.
"""

from __future__ import annotations

from typing import Any

from app.database import session_scope
from app.logging_config import get_logger
from app.models import Post
from app.services import jobs, publisher
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.publish_post", bind=True, max_retries=0)
def publish_post_task(self, post_id: str) -> dict[str, Any]:  # noqa: ARG001
    """Publica un post.

    Los reintentos NO los gestiona Celery, sino la base de datos
    (`next_retry_at` + barredor), para que el trabajo sobreviva al reinicio
    del worker.
    """
    with session_scope() as db:
        if not publisher.claim_post(db, post_id):
            logger.debug("tasks: el post %s ya estaba reclamado", post_id)
            return {"post_id": post_id, "status": "already_claimed"}
        post = db.get(Post, post_id)
        if post is None:
            logger.warning("tasks: el post %s no existe", post_id)
            return {"post_id": post_id, "status": "not_found"}
        return publisher.publish_post(db, post).to_dict()


@celery_app.task(name="app.workers.tasks.sweep_scheduled_posts")
def sweep_scheduled_posts() -> dict[str, int]:
    return jobs.sweep_scheduled_posts()


@celery_app.task(name="app.workers.tasks.retry_pending_posts")
def retry_pending_posts() -> dict[str, int]:
    return jobs.retry_pending_posts()


@celery_app.task(name="app.workers.tasks.sync_stuck_posts")
def sync_stuck_posts() -> dict[str, int]:
    return jobs.sync_stuck_posts()


@celery_app.task(name="app.workers.tasks.refresh_expiring_tokens")
def refresh_expiring_tokens() -> dict[str, int]:
    return jobs.refresh_expiring_tokens()


@celery_app.task(name="app.workers.tasks.purge_expired_media")
def purge_expired_media() -> dict[str, int]:
    return jobs.purge_expired_media()


@celery_app.task(name="app.workers.tasks.purge_oauth_states")
def purge_oauth_states() -> dict[str, int]:
    return jobs.purge_oauth_states()


@celery_app.task(name="app.workers.tasks.sync_post")
def sync_post_task(post_id: str) -> dict[str, Any]:
    return jobs.sync_post(post_id)
