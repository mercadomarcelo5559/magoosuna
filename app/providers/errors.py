"""Errores de providers, clasificados para decidir reintentos."""

from __future__ import annotations

from typing import Any, TypedDict

from app.models.enums import ErrorCategory


class ErrorContext(TypedDict, total=False):
    """Contexto común de un error de plataforma.

    Es un `TypedDict` para poder pasarlo con `**contexto` conservando los
    tipos de cada campo.
    """

    http_status: int | None
    platform_code: str | None
    stage: str | None
    details: dict[str, Any] | None


class ProviderError(Exception):
    """Error al hablar con una plataforma social.

    `category` determina la política de reintentos (ver app.services.retry).
    """

    category: ErrorCategory = ErrorCategory.INTERNAL

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        platform_code: str | None = None,
        stage: str | None = None,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.platform_code = platform_code
        self.stage = stage
        self.retry_after = retry_after
        self.details = details or {}

    @property
    def retryable(self) -> bool:
        return self.category.retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "category": str(self.category),
            "http_status": self.http_status,
            "platform_code": self.platform_code,
            "stage": self.stage,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:
        parts = [self.message]
        if self.platform_code:
            parts.append(f"code={self.platform_code}")
        if self.http_status:
            parts.append(f"http={self.http_status}")
        return " | ".join(parts)


class TransientProviderError(ProviderError):
    """Fallo temporal (5xx, timeout, red). Se reintenta."""

    category = ErrorCategory.TRANSIENT


class RateLimitError(ProviderError):
    """La plataforma aplicó rate limit. Se reintenta respetando `retry_after`."""

    category = ErrorCategory.RATE_LIMIT


class AuthenticationError(ProviderError):
    """Token inválido/expirado sin posibilidad de refresh. Requiere reconectar."""

    category = ErrorCategory.AUTH


class PermanentProviderError(ProviderError):
    """La plataforma rechazó la petición de forma definitiva."""

    category = ErrorCategory.PERMANENT


class ConfigurationError(ProviderError):
    """Falta configuración local (client id/secret, redirect URI, permisos)."""

    category = ErrorCategory.CONFIGURATION


class InvalidVideoError(ProviderError):
    """El video no cumple los requisitos de la plataforma."""

    category = ErrorCategory.INVALID_VIDEO


class ProcessingTimeoutError(ProviderError):
    """La plataforma no terminó de procesar el video dentro del plazo."""

    category = ErrorCategory.PROCESSING_TIMEOUT


#: HTTP → excepción, para clasificar respuestas genéricas.
def error_for_status(
    status: int,
    message: str,
    *,
    platform_code: str | None = None,
    stage: str | None = None,
    retry_after: int | None = None,
    details: dict | None = None,
) -> ProviderError:
    contexto: ErrorContext = {
        "http_status": status,
        "platform_code": platform_code,
        "stage": stage,
        "details": details,
    }
    if status == 429:
        return RateLimitError(message, retry_after=retry_after, **contexto)
    if status in (401, 403):
        return AuthenticationError(message, **contexto)
    if status in (408, 409, 425) or status >= 500:
        return TransientProviderError(message, retry_after=retry_after, **contexto)
    return PermanentProviderError(message, **contexto)
