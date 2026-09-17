"""Punto de entrada de la API FastAPI.

Arranque en desarrollo:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Documentación interactiva:
    http://localhost:8000/docs
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import settings
from app.database import SessionLocal, create_all, database_is_reachable
from app.logging_config import configure_logging, get_logger
from app.providers.errors import ProviderError
from app.providers.registry import UnsupportedPlatformError
from app.routers import accounts, admin, health, media, oauth, posts, webhooks
from app.schemas import ErrorDetail
from app.security.crypto import CryptoError
from app.services import dispatch
from app.services.clients import ensure_bootstrap_keys
from app.services.runner import shutdown_runner
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.utils.video import VideoValidationError

configure_logging()
logger = get_logger(__name__)

DESCRIPTION = """
API independiente para **gestionar y publicar videos en redes sociales**
(Instagram, TikTok y YouTube), consumible desde cualquier cliente — por ejemplo
una app de **Macaly**.

### Autenticación
Todas las rutas (salvo `/health`, `/v1/platforms`, los callbacks OAuth, la
descarga firmada de media y los webhooks) requieren una API key:

```
Authorization: Bearer <API_KEY>
```

### Flujo típico
1. `GET  /v1/oauth/{platform}/authorize` → abrir la URL en el navegador del usuario.
2. `POST /v1/media` → subir el video (o `POST /v1/media/from-url`).
3. `POST /v1/posts` → publicar en una o varias plataformas (o programar).
4. `GET  /v1/posts/{id}` → consultar el estado.

### Idempotencia
Envía la cabecera `Idempotency-Key` en `POST /v1/posts` para que un reintento
de la misma petición no publique dos veces.
"""

TAGS_METADATA = [
    {"name": "salud", "description": "Estado del servicio y plataformas soportadas."},
    {"name": "oauth", "description": "Conectar cuentas de Instagram, TikTok y YouTube."},
    {"name": "cuentas", "description": "Listar, refrescar y desconectar cuentas."},
    {"name": "media", "description": "Subida y gestión temporal de videos."},
    {"name": "publicaciones", "description": "Publicar, programar y consultar estados."},
    {"name": "webhooks", "description": "Eventos entrantes de las plataformas."},
    {"name": "administración", "description": "Clientes y rotación de API keys."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Comprueba la configuración crítica y arranca el scheduler embebido."""
    logger.info(
        "Arrancando %s v%s (entorno=%s, base de datos=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        "sqlite" if settings.is_sqlite else "postgresql",
    )

    if not settings.encryption_key:
        logger.error(
            "ENCRYPTION_KEY no está configurada: no se podrán guardar tokens OAuth. "
            "Genera una con: python -m app.security.crypto --generate-key"
        )
    if not settings.signing_secret:
        logger.error(
            "SIGNING_SECRET no está configurada: no se podrán firmar las URLs de media. "
            "Genera una con: python -m app.security.crypto --generate-secret"
        )

    if settings.is_sqlite:
        # En desarrollo con SQLite creamos el esquema directamente para que
        # la API funcione sin ejecutar Alembic. Con PostgreSQL usa `alembic upgrade head`.
        create_all()
        logger.info("Esquema SQLite creado/verificado")
    elif not database_is_reachable():
        logger.error(
            "No se puede conectar a la base de datos (%s). "
            "¿Está PostgreSQL levantado? `docker compose up -d postgres`",
            settings.database_url.split("@")[-1],
        )

    if database_is_reachable():
        db = SessionLocal()
        try:
            ensure_bootstrap_keys(db)
        except Exception as exc:
            logger.warning("No se pudieron registrar las bootstrap API keys: %s", exc)
        finally:
            db.close()

    logger.info("Modo de publicación: %s (%s)", settings.publish_mode, dispatch.describe_mode())
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        shutdown_runner()
        logger.info("API detenida")


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=__version__,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Social Video API"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key"],
    expose_headers=[
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Registra cada request con id, duración y resultado. Sin secretos."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "request_id=%s %s %s → excepción no controlada (%.1f ms)",
            request_id,
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s client_id=%s %s %s → %s (%.1f ms)",
        request_id,
        getattr(request.state, "client_id", "-"),
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ------------------------------------------------------------- errores
def _error_response(
    status_code: int, error: str, message: str, details: dict | None = None
) -> JSONResponse:
    payload = ErrorDetail(error=error, message=message, details=details)
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normaliza los errores HTTP al formato `ErrorDetail`."""
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        response = _error_response(
            exc.status_code,
            str(detail.get("error") or "http_error"),
            str(detail["message"]),
            detail.get("details"),
        )
    else:
        code_map = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "rate_limited",
            501: "not_configured",
            503: "unavailable",
        }
        response = _error_response(
            exc.status_code,
            code_map.get(exc.status_code, "http_error"),
            str(detail),
        )
    for key, value in (exc.headers or {}).items():
        response.headers[key] = value
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Errores de validación de Pydantic con el campo problemático."""
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())[1:]) or "body",
            "message": error.get("msg", "valor inválido"),
            "type": error.get("type"),
        }
        for error in exc.errors()
    ]
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        "La petición no es válida",
        {"errors": errors},
    )


@app.exception_handler(VideoValidationError)
async def video_validation_handler(_request: Request, exc: VideoValidationError) -> JSONResponse:
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "invalid_video",
        exc.message,
        {"field": exc.field},
    )


@app.exception_handler(UnsupportedPlatformError)
async def unsupported_platform_handler(
    _request: Request, exc: UnsupportedPlatformError
) -> JSONResponse:
    return _error_response(
        status.HTTP_400_BAD_REQUEST,
        "unsupported_platform",
        str(exc),
        {"platform": exc.platform},
    )


@app.exception_handler(ProviderError)
async def provider_error_handler(_request: Request, exc: ProviderError) -> JSONResponse:
    """Errores de las plataformas, con su categoría para decidir reintentos."""
    status_code = (
        status.HTTP_401_UNAUTHORIZED
        if exc.category.value == "auth"
        else status.HTTP_429_TOO_MANY_REQUESTS
        if exc.category.value == "rate_limit"
        else status.HTTP_501_NOT_IMPLEMENTED
        if exc.category.value == "configuration"
        else status.HTTP_502_BAD_GATEWAY
    )
    return _error_response(
        status_code, f"provider_{exc.category.value}", exc.message, exc.to_dict()
    )


@app.exception_handler(CryptoError)
async def crypto_error_handler(_request: Request, exc: CryptoError) -> JSONResponse:
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "encryption_error",
        str(exc),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Último recurso: no filtra detalles internos al cliente."""
    logger.exception("Excepción no controlada: %s", exc)
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Error interno del servidor. Revisa los logs del servicio.",
    )


# ------------------------------------------------------------- routers
app.include_router(health.router)
app.include_router(health.router, prefix=settings.api_prefix, include_in_schema=False)
app.include_router(oauth.router, prefix=settings.api_prefix)
app.include_router(accounts.router, prefix=settings.api_prefix)
app.include_router(media.router, prefix=settings.api_prefix)
app.include_router(posts.router, prefix=settings.api_prefix)
app.include_router(webhooks.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, object]:
    return {
        "name": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
        "api_prefix": settings.api_prefix,
    }
