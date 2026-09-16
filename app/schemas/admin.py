"""Schemas de administración (alta de clientes y API keys)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CreateClientRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Macaly", "email": "tu@correo.com"}}
    )

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None


class IssuedApiKeyResponse(BaseModel):
    """La API key en claro sólo se devuelve en esta respuesta, una vez."""

    api_key: str = Field(description="Guárdala ahora: no se puede volver a consultar")
    key: ApiKeyResponse


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str | None = None
    is_active: bool
    created_at: datetime


class CreateClientResponse(BaseModel):
    client: ClientResponse
    api_key: str = Field(description="API key inicial. Guárdala ahora.")


class CreateApiKeyRequest(BaseModel):
    label: str = Field(default="default", max_length=120)
    expires_at: datetime | None = None


class RotateApiKeyRequest(BaseModel):
    revoke_key_id: str | None = Field(
        default=None, description="Id de la key a revocar tras emitir la nueva"
    )
    label: str = Field(default="rotated", max_length=120)
