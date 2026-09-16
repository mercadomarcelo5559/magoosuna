"""Aplicación Celery.

En desarrollo (Codespaces) se puede trabajar de dos formas:
  * Con Redis:  `celery -A app.workers.celery_app worker -B --concurrency=2`
  * Sin Redis:  `CELERY_TASK_ALWAYS_EAGER=true` → las tareas corren en proceso.

El worker es un proceso independiente: mover la publicación a un servidor
permanente en producción no requiere cambiar la lógica de negocio.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.logging_config import configure_logging

configure_logging()

celery_app = Celery(
    "social_video_api",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Codespaces es una máquina pequeña: 2 procesos son suficientes.
    worker_concurrency=2,
    worker_max_tasks_per_child=100,
    broker_connection_retry_on_startup=True,
    result_expires=7 * 24 * 3600,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
    task_soft_time_limit=settings.processing_timeout_seconds + 300,
    task_time_limit=settings.processing_timeout_seconds + 600,
    task_default_queue="publishing",
    beat_schedule={
        # Fuente de verdad en base de datos: recupera lo vencido tras caídas.
        "sweep-scheduled-posts": {
            "task": "app.workers.tasks.sweep_scheduled_posts",
            "schedule": float(settings.scheduler_interval_seconds),
        },
        "retry-pending-posts": {
            "task": "app.workers.tasks.retry_pending_posts",
            "schedule": 60.0,
        },
        "sync-stuck-posts": {
            "task": "app.workers.tasks.sync_stuck_posts",
            "schedule": 300.0,
        },
        "refresh-expiring-tokens": {
            "task": "app.workers.tasks.refresh_expiring_tokens",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "purge-expired-media": {
            "task": "app.workers.tasks.purge_expired_media",
            "schedule": crontab(minute=30, hour="*"),
        },
        "purge-oauth-states": {
            "task": "app.workers.tasks.purge_oauth_states",
            "schedule": crontab(minute=15, hour="*/3"),
        },
    },
)
