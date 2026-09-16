"""Cliente HTTP compartido por los providers, con clasificación de errores."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.providers.errors import (
    ProviderError,
    TransientProviderError,
    error_for_status,
)

logger = get_logger(__name__)


def build_client(
    *, timeout: float | None = None, base_url: str = "", follow_redirects: bool = True
) -> httpx.Client:
    """Crea un `httpx.Client` con timeouts sensatos."""
    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout or settings.http_timeout_seconds),
        follow_redirects=follow_redirects,
        headers={"User-Agent": f"{settings.app_name}/1.0"},
    )


def parse_retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def json_body(response: httpx.Response) -> dict[str, Any]:
    """Cuerpo JSON de una respuesta, o `{}` si no es JSON válido."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"data": data}


def request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    stage: str,
    error_parser: Any = None,
    **kwargs: Any,
) -> httpx.Response:
    """Ejecuta una petición y convierte los fallos en `ProviderError`.

    `error_parser(response) -> ProviderError | None` permite que cada provider
    traduzca sus propios códigos de error antes del mapeo genérico por HTTP.
    """
    try:
        response = client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise TransientProviderError(f"Timeout en {stage}: {exc}", stage=stage) from exc
    except httpx.TransportError as exc:
        raise TransientProviderError(f"Error de red en {stage}: {exc}", stage=stage) from exc

    if response.is_success:
        return response

    if error_parser is not None:
        parsed = error_parser(response)
        if isinstance(parsed, ProviderError):
            parsed.stage = parsed.stage or stage
            raise parsed

    body = response.text[:600]
    raise error_for_status(
        response.status_code,
        f"{stage} falló ({response.status_code}): {body}",
        stage=stage,
        retry_after=parse_retry_after(response),
    )
