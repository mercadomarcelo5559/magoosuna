"""Endpoints de salud y descubrimiento de plataformas."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.database import database_is_reachable
from app.providers import platform_status
from app.schemas import ComponentHealth, HealthResponse, PlatformInfo
from app.services import dispatch
from app.services.media import public_url_is_reachable
from app.services.scheduler import scheduler_is_running

router = APIRouter(tags=["salud"])


def _redis_healthy() -> tuple[bool, str | None]:
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url, socket_timeout=1, socket_connect_timeout=1
        )
        client.ping()
        return True, None
    except Exception as exc:
        return False, str(exc)[:200]


@router.get("/health", response_model=HealthResponse, summary="Estado del servicio")
def health() -> HealthResponse:
    """Comprueba base de datos, Redis, almacenamiento y scheduler.

    Se usa en el `healthcheck` de Docker Compose y para diagnosticar el entorno.
    """
    components: list[ComponentHealth] = []

    db_ok = database_is_reachable()
    components.append(
        ComponentHealth(
            name="database",
            healthy=db_ok,
            detail="sqlite" if settings.is_sqlite else "postgresql",
        )
    )

    if settings.needs_redis:
        redis_ok, redis_error = _redis_healthy()
        components.append(
            ComponentHealth(name="redis", healthy=redis_ok, detail=redis_error or "ok")
        )
    else:
        # En modo "solo"/"inline" la cola es la base de datos: Redis no hace falta.
        components.append(
            ComponentHealth(
                name="redis",
                healthy=True,
                detail=f"no se usa (modo {settings.publish_mode})",
            )
        )

    from app.storage import get_storage

    try:
        storage_name = get_storage().name
        storage_ok = True
        storage_detail = storage_name
    except Exception as exc:
        storage_ok = False
        storage_detail = str(exc)[:200]
    components.append(ComponentHealth(name="storage", healthy=storage_ok, detail=storage_detail))

    components.append(
        ComponentHealth(
            name="scheduler",
            healthy=True,
            detail=("en proceso (activo)" if scheduler_is_running() else "externo (celery beat)"),
        )
    )
    components.append(
        ComponentHealth(
            name="publisher",
            healthy=True,
            detail=f"{settings.publish_mode}: {dispatch.describe_mode()}",
        )
    )
    components.append(
        ComponentHealth(
            name="public_url",
            healthy=public_url_is_reachable(),
            detail=(
                settings.public_base_url
                if public_url_is_reachable()
                else f"{settings.public_base_url} no es HTTPS pública: Instagram "
                "no podrá descargar los videos (usa un túnel o S3/R2)"
            ),
        )
    )

    # Redis en modo eager no invalida el servicio; la BD sí.
    critical_ok = db_ok and storage_ok
    return HealthResponse(
        status="ok" if critical_ok else "degraded",
        version=__version__,
        environment=settings.environment,
        components=components,
    )


@router.get(
    "/platforms",
    response_model=list[PlatformInfo],
    summary="Plataformas soportadas y su configuración",
)
def platforms() -> list[PlatformInfo]:
    """Indica qué plataformas están soportadas y si tienen credenciales."""
    rows = platform_status()
    return [
        PlatformInfo(
            platform=str(row["platform"]),
            configured=bool(row["configured"]),
            requires_public_video_url=bool(row["requires_public_video_url"]),
            docs_url=str(row["docs_url"]),
            connect_url=(
                f"{settings.api_prefix}/oauth/{row['platform']}/authorize"
                if row["configured"]
                else None
            ),
        )
        for row in rows
    ]
