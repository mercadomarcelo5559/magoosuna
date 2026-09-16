"""Schemas compartidos: errores, paginación, salud."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Cuerpo de error uniforme de la API."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "validation_error",
                "message": "El MIME type 'video/avi' no está permitido",
                "details": {"field": "file"},
            }
        }
    )

    error: str = Field(description="Código de error estable, apto para programar contra él")
    message: str = Field(description="Descripción legible del problema")
    details: dict[str, Any] | None = Field(default=None, description="Contexto adicional")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total de elementos que cumplen el filtro")
    limit: int
    offset: int


class ComponentHealth(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(description="`ok` o `degraded`")
    version: str
    environment: str
    components: list[ComponentHealth]


class PlatformInfo(BaseModel):
    platform: str
    configured: bool = Field(description="True si hay credenciales en el entorno")
    requires_public_video_url: bool
    docs_url: str
    connect_url: str | None = Field(
        default=None, description="Endpoint para iniciar el OAuth de esta plataforma"
    )


class MessageResponse(BaseModel):
    message: str
