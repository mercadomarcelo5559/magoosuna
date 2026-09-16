"""Administración: clientes y rotación de API keys.

Protegido por `ADMIN_API_KEYS` (distinta de las API keys de cliente). Si esa
variable está vacía, estos endpoints devuelven 503 y quedan deshabilitados.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import AdminAuth, DbSession
from app.logging_config import get_logger
from app.models import ApiKey, Client
from app.schemas import (
    ApiKeyResponse,
    ClientResponse,
    CreateApiKeyRequest,
    CreateClientRequest,
    CreateClientResponse,
    IssuedApiKeyResponse,
    MessageResponse,
    RotateApiKeyRequest,
)
from app.services import clients as clients_service

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["administración"])


@router.post(
    "/clients",
    response_model=CreateClientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un cliente y su primera API key",
)
def create_client(
    payload: CreateClientRequest, _admin: AdminAuth, db: DbSession
) -> CreateClientResponse:
    """Crea el cliente (por ejemplo Macaly) y devuelve su API key inicial.

    La API key en claro sólo se muestra en esta respuesta: guárdala.
    """
    client = clients_service.create_client(
        db, name=payload.name, email=str(payload.email) if payload.email else None
    )
    issued = clients_service.issue_api_key(db, client, label="initial")
    return CreateClientResponse(
        client=ClientResponse.model_validate(client), api_key=issued.api_key
    )


@router.get("/clients", response_model=list[ClientResponse], summary="Listar clientes")
def list_clients(_admin: AdminAuth, db: DbSession) -> list[ClientResponse]:
    rows = list(db.scalars(select(Client).order_by(Client.created_at.desc())))
    return [ClientResponse.model_validate(row) for row in rows]


def _get_client(db, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No existe el cliente {client_id}"
        )
    return client


@router.get(
    "/clients/{client_id}/api-keys",
    response_model=list[ApiKeyResponse],
    summary="Listar las API keys de un cliente",
)
def list_api_keys(client_id: str, _admin: AdminAuth, db: DbSession) -> list[ApiKeyResponse]:
    _get_client(db, client_id)
    return [
        ApiKeyResponse.model_validate(row) for row in clients_service.list_api_keys(db, client_id)
    ]


@router.post(
    "/clients/{client_id}/api-keys",
    response_model=IssuedApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Emitir una API key nueva",
)
def create_api_key(
    client_id: str, payload: CreateApiKeyRequest, _admin: AdminAuth, db: DbSession
) -> IssuedApiKeyResponse:
    client = _get_client(db, client_id)
    issued = clients_service.issue_api_key(
        db, client, label=payload.label, expires_at=payload.expires_at
    )
    return IssuedApiKeyResponse(
        api_key=issued.api_key, key=ApiKeyResponse.model_validate(issued.record)
    )


@router.post(
    "/clients/{client_id}/api-keys/rotate",
    response_model=IssuedApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rotar una API key (emite una nueva y revoca la anterior)",
)
def rotate_api_key(
    client_id: str, payload: RotateApiKeyRequest, _admin: AdminAuth, db: DbSession
) -> IssuedApiKeyResponse:
    """Rotación de claves del punto 17 de los requisitos."""
    client = _get_client(db, client_id)
    old: ApiKey | None = None
    if payload.revoke_key_id:
        old = db.get(ApiKey, payload.revoke_key_id)
        if old is None or old.client_id != client_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No existe la API key {payload.revoke_key_id} para este cliente",
            )
    issued = clients_service.rotate_api_key(db, client, old=old, label=payload.label)
    return IssuedApiKeyResponse(
        api_key=issued.api_key, key=ApiKeyResponse.model_validate(issued.record)
    )


@router.delete(
    "/api-keys/{key_id}",
    response_model=MessageResponse,
    summary="Revocar una API key",
)
def revoke_api_key(key_id: str, _admin: AdminAuth, db: DbSession) -> MessageResponse:
    record = db.get(ApiKey, key_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No existe la API key {key_id}"
        )
    clients_service.revoke_api_key(db, record)
    return MessageResponse(message=f"API key {record.key_prefix}… revocada")
