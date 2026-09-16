"""Política de reintentos: exponential backoff con jitter por categoría."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.config import settings
from app.models import ErrorCategory, utcnow
from app.providers.errors import ProviderError

#: Multiplicador de espera base por categoría de error.
_CATEGORY_MULTIPLIER: dict[ErrorCategory, float] = {
    ErrorCategory.TRANSIENT: 1.0,
    ErrorCategory.INTERNAL: 1.0,
    ErrorCategory.RATE_LIMIT: 4.0,
    ErrorCategory.PROCESSING_TIMEOUT: 2.0,
}


def classify(exc: BaseException) -> ErrorCategory:
    """Clasifica cualquier excepción en una categoría del dominio."""
    if isinstance(exc, ProviderError):
        return exc.category
    if isinstance(exc, TimeoutError):
        return ErrorCategory.TRANSIENT
    if isinstance(exc, ConnectionError | OSError):
        return ErrorCategory.TRANSIENT
    if isinstance(exc, ValueError):
        return ErrorCategory.PERMANENT
    return ErrorCategory.INTERNAL


def should_retry(category: ErrorCategory, attempt: int) -> bool:
    """True si conviene reintentar dado el número de intentos ya realizados."""
    if not category.retryable:
        return False
    return attempt < settings.max_publish_attempts


def compute_backoff(
    category: ErrorCategory, attempt: int, *, retry_after: int | None = None
) -> timedelta:
    """Backoff exponencial con jitter, respetando `Retry-After` si existe.

    `attempt` es el número de intentos ya consumidos (1 tras el primer fallo).
    """
    if retry_after and retry_after > 0:
        capped = min(retry_after, settings.retry_max_delay_seconds)
        return timedelta(seconds=capped)

    multiplier = _CATEGORY_MULTIPLIER.get(category, 1.0)
    base = settings.retry_base_delay_seconds * multiplier
    delay = base * (2 ** max(attempt - 1, 0))
    delay = min(delay, settings.retry_max_delay_seconds)
    # Jitter del ±20 % para no sincronizar reintentos entre posts.
    jitter = delay * 0.2
    delay = max(1.0, delay + random.uniform(-jitter, jitter))  # noqa: S311 - no cripto
    return timedelta(seconds=round(delay, 3))


def next_retry_at(
    category: ErrorCategory, attempt: int, *, retry_after: int | None = None
) -> datetime:
    return utcnow() + compute_backoff(category, attempt, retry_after=retry_after)


def retry_after_from(exc: BaseException) -> int | None:
    return getattr(exc, "retry_after", None)
