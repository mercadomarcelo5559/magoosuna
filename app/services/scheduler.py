"""Scheduler en proceso (APScheduler) para desarrollo en Codespaces.

En producción el barredor lo ejecuta `celery beat` en un proceso aparte. Aquí
se ofrece la MISMA lógica embebida en el proceso de la API para que todo
funcione con un solo comando mientras el Codespace esté encendido.

IMPORTANTE: un Codespace detenido no publica nada. Para publicaciones
programadas 24/7 hace falta un servidor permanente (ver README → Producción).
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run(task_name: str, func) -> None:
    """Ejecuta una tarea capturando errores para no matar el scheduler."""
    try:
        result = func()
        if result:
            logger.debug("scheduler: %s → %s", task_name, result)
    except Exception as exc:
        logger.exception("scheduler: %s falló: %s", task_name, exc)


def start_scheduler() -> BackgroundScheduler | None:
    """Arranca el scheduler embebido si `SCHEDULER_IN_PROCESS` está activo."""
    global _scheduler
    if not settings.scheduler_in_process:
        logger.info("scheduler en proceso desactivado: usa `celery -A app.workers.celery_app beat`")
        return None
    if _scheduler is not None:
        return _scheduler

    from app.workers import tasks

    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )

    scheduler.add_job(
        lambda: _run("sweep_scheduled_posts", tasks.sweep_scheduled_posts),
        trigger=IntervalTrigger(seconds=settings.scheduler_interval_seconds),
        id="sweep_scheduled_posts",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("retry_pending_posts", tasks.retry_pending_posts),
        trigger=IntervalTrigger(seconds=60),
        id="retry_pending_posts",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("sync_stuck_posts", tasks.sync_stuck_posts),
        trigger=IntervalTrigger(minutes=5),
        id="sync_stuck_posts",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("refresh_expiring_tokens", tasks.refresh_expiring_tokens),
        trigger=IntervalTrigger(hours=6),
        id="refresh_expiring_tokens",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("purge_expired_media", tasks.purge_expired_media),
        trigger=IntervalTrigger(hours=1),
        id="purge_expired_media",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("purge_oauth_states", tasks.purge_oauth_states),
        trigger=IntervalTrigger(hours=3),
        id="purge_oauth_states",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "scheduler en proceso activo (barrido cada %ss). " "Codespaces NO es un servidor 24/7.",
        settings.scheduler_interval_seconds,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler en proceso detenido")


def scheduler_is_running() -> bool:
    return _scheduler is not None and _scheduler.running
