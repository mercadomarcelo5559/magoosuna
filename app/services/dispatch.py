"""Punto único de encolado de publicaciones.

Abstrae CÓMO se ejecuta una publicación, para que los routers y las tareas
periódicas no dependan del modo elegido:

* ``inline``  — se publica en el acto, en el mismo hilo (tests y depuración).
* ``solo``    — se publica en un hilo del propio proceso de la API.
                Un solo servicio, sin Redis ni worker aparte. Es el modo
                recomendado para un VPS pequeño.
* ``celery``  — se encola en Redis y la ejecuta un worker Celery aparte.
                Para cuando haga falta escalar horizontalmente.

Cambiar de modo NO cambia la lógica de negocio: los tres acaban llamando a
``app.services.publisher.publish_post``.
"""

from __future__ import annotations

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def enqueue_post(post_id: str, *, countdown: float | None = None) -> None:
    """Programa la publicación de un post según el modo configurado."""
    modo = settings.publish_mode

    if modo == "celery":
        from app.workers.tasks import publish_post_task

        publish_post_task.apply_async(args=[post_id], countdown=countdown or None)
        return

    from app.services.runner import get_runner

    runner = get_runner()
    if modo == "inline":
        runner.run_now(post_id)
    else:
        runner.submit(post_id, countdown=countdown)


def describe_mode() -> str:
    """Texto legible del modo activo, para `/health`."""
    return {
        "inline": "en el propio proceso (síncrono)",
        "solo": "en el propio proceso (hilos)",
        "celery": "worker Celery externo",
    }.get(settings.publish_mode, settings.publish_mode)
