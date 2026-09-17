"""Ejecutor de publicaciones dentro del proceso de la API (modo ``solo``).

Permite desplegar TODO en un único servicio: la API, el worker y el
planificador comparten proceso y la base de datos hace de cola. Es lo que
convierte un VPS de 5 €/mes en suficiente para producción.

La reclamación de trabajos es atómica en base de datos, así que sigue siendo
correcta aunque se arranquen varios procesos de uvicorn.
"""

from __future__ import annotations

import atexit
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.database import session_scope
from app.logging_config import get_logger
from app.models import Post

logger = get_logger(__name__)


class PublishRunner:
    """Pool de hilos que publica posts reclamándolos de la base de datos."""

    def __init__(self, max_workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="publicador")
        self._cerrado = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------- ejecución
    def submit(self, post_id: str, *, countdown: float | None = None) -> None:
        """Encola la publicación en segundo plano (no bloquea la petición)."""
        with self._lock:
            if self._cerrado:
                logger.warning("runner: cerrado; el post %s lo recogerá el barredor", post_id)
                return
            self._pool.submit(self._ejecutar, post_id, countdown)

    def run_now(self, post_id: str) -> None:
        """Publica de forma síncrona (modo ``inline``)."""
        self._ejecutar(post_id, None)

    def _ejecutar(self, post_id: str, countdown: float | None) -> None:
        if countdown and countdown > 0:
            time.sleep(min(countdown, 60))
        try:
            publicar_post_reclamado(post_id)
        except Exception as exc:
            logger.exception("runner: fallo publicando post_id=%s: %s", post_id, exc)

    def shutdown(self) -> None:
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        logger.info("runner: detenido")


def publicar_post_reclamado(post_id: str) -> None:
    """Reclama el post y lo publica. Si otro proceso lo tiene, no hace nada."""
    from app.services import publisher

    with session_scope() as db:
        if not publisher.claim_post(db, post_id):
            logger.debug("runner: post %s ya reclamado por otro proceso", post_id)
            return
        post = db.get(Post, post_id)
        if post is None:
            logger.warning("runner: el post %s ya no existe", post_id)
            return
        publisher.publish_post(db, post)


_runner: PublishRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> PublishRunner:
    """Devuelve el runner del proceso, creándolo la primera vez."""
    global _runner
    if _runner is None:
        with _runner_lock:
            if _runner is None:
                _runner = PublishRunner(max_workers=settings.publish_concurrency)
                atexit.register(_runner.shutdown)
                logger.info(
                    "runner: activo con %s hilos de publicación",
                    settings.publish_concurrency,
                )
    return _runner


def shutdown_runner() -> None:
    global _runner
    if _runner is not None:
        _runner.shutdown()
        _runner = None
