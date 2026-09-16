"""Dependencias de FastAPI: autenticación, rate limiting y paginación."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.models import ApiKey, Client
from app.security.crypto import constant_time_equals
from app.services import clients as clients_service
from app.services import rate_limit

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="API key",
    description=(
        "Autenticación de la API. Envía `Authorization: Bearer <API_KEY>`. "
        "También se acepta la cabecera `X-API-Key`."
    ),
)

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(slots=True)
class AuthContext:
    """Cliente autenticado y la API key con la que se autenticó."""

    client: Client
    api_key: ApiKey

    @property
    def client_id(self) -> str:
        return self.client.id


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def extract_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """Obtiene la API key de `Authorization: Bearer` o de `X-API-Key`."""
    if credentials and credentials.credentials:
        return credentials.credentials.strip()
    if x_api_key:
        return x_api_key.strip()
    raise _unauthorized("Falta la API key. Envía `Authorization: Bearer <API_KEY>` o `X-API-Key`.")


def get_auth(
    request: Request,
    response: Response,
    db: DbSession,
    api_key: Annotated[str, Depends(extract_api_key)],
) -> AuthContext:
    """Autentica la petición y aplica rate limiting por API key."""
    record = clients_service.resolve_api_key(db, api_key)
    if record is None:
        logger.warning(
            "auth: API key inválida path=%s ip=%s",
            request.url.path,
            request.client.host if request.client else "?",
        )
        raise _unauthorized("API key inválida, revocada o caducada")

    result = rate_limit.check(f"client:{record.client_id}")
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_after)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Límite de {result.limit} peticiones por "
                f"{settings.rate_limit_window_seconds}s superado"
            ),
            headers={"Retry-After": str(result.reset_after)},
        )

    clients_service.touch_api_key(db, record)
    request.state.client_id = record.client_id
    return AuthContext(client=record.client, api_key=record)


CurrentAuth = Annotated[AuthContext, Depends(get_auth)]


def require_admin(
    api_key: Annotated[str, Depends(extract_api_key)],
) -> str:
    """Protege los endpoints de administración con `ADMIN_API_KEYS`."""
    admin_keys = settings.admin_api_key_list
    if not admin_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Los endpoints de administración están deshabilitados: define "
                "ADMIN_API_KEYS en el .env para habilitarlos."
            ),
        )
    if not any(constant_time_equals(api_key, candidate) for candidate in admin_keys):
        raise _unauthorized("API key de administración inválida")
    return api_key


AdminAuth = Annotated[str, Depends(require_admin)]


@dataclass(slots=True)
class Pagination:
    limit: int
    offset: int


def pagination(limit: int = 20, offset: int = 0) -> Pagination:
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`limit` debe estar entre 1 y 100",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`offset` no puede ser negativo",
        )
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]


def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """Lee y valida la cabecera `Idempotency-Key`."""
    if idempotency_key is None:
        return None
    key = idempotency_key.strip()
    if not key:
        return None
    if len(key) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`Idempotency-Key` no puede superar 255 caracteres",
        )
    return key


IdempotencyKeyDep = Annotated[str | None, Depends(idempotency_key)]
