"""Webhooks de plataformas.

Estado actual de las plataformas soportadas (comprobado en su documentación):

  * **Instagram**: Meta ofrece webhooks de Instagram para mensajes, comentarios
    y menciones, pero NO notifica el fin de procesado de un contenedor de
    publicación. Por eso el estado del contenedor se consulta con polling
    controlado (`status_code`, 1 vez cada `PROCESSING_POLL_INTERVAL_SECONDS`).
    Este endpoint implementa la verificación `hub.challenge` y la validación de
    firma `X-Hub-Signature-256` para los eventos que sí existen.

  * **TikTok**: la Content Posting API no ofrece webhooks de estado de
    publicación; se usa `/v2/post/publish/status/fetch/` (polling).

  * **YouTube**: dispone de PubSubHubbub para notificar videos nuevos de un
    canal, no el progreso de una subida concreta. Se usa `videos.list` para el
    estado de procesado.

Cuando cualquiera de estas plataformas publique webhooks oficiales de estado,
basta con añadir aquí el handler correspondiente: el resto del sistema ya está
preparado (`publisher.sync_post_status`).
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.logging_config import get_logger
from app.models import Platform

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_meta_signature(body: bytes, signature: str | None) -> bool:
    """Valida `X-Hub-Signature-256` con el App Secret de Meta."""
    if not signature or not settings.instagram_app_secret:
        return False
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(settings.instagram_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[len("sha256=") :])


@router.get(
    "/instagram",
    response_class=PlainTextResponse,
    summary="Verificación del webhook de Instagram (hub.challenge)",
)
def verify_instagram_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
) -> str:
    """Meta llama aquí al configurar el webhook en el panel de la app.

    El `verify_token` que configures en Meta debe coincidir con `SIGNING_SECRET`.
    """
    expected = settings.signing_secret
    if hub_mode != "subscribe" or not expected or hub_verify_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verify_token inválido")
    return hub_challenge


@router.post("/instagram", summary="Recepción de eventos de Instagram")
async def instagram_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Recibe eventos de Instagram con la firma verificada.

    Meta no envía el estado de publicación, así que registramos el evento sin
    secretos y devolvemos 200 para que no se reintente indefinidamente.
    """
    body = await request.body()
    if not _verify_meta_signature(body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Firma del webhook inválida"
        )
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    entries = payload.get("entry") or []
    logger.info(
        "webhook: instagram recibido object=%s entradas=%s",
        payload.get("object"),
        len(entries),
    )
    return {"status": "received", "platform": Platform.INSTAGRAM.value}


@router.get(
    "/status",
    summary="Qué plataformas notifican por webhook y cuáles por polling",
)
def webhook_status() -> dict[str, dict[str, object]]:
    """Documenta la estrategia de actualización de estado por plataforma."""
    return {
        Platform.INSTAGRAM.value: {
            "publish_status_webhook": False,
            "strategy": "polling del status_code del contenedor",
            "poll_interval_seconds": settings.processing_poll_interval_seconds,
            "webhook_endpoint": f"{settings.api_prefix}/webhooks/instagram",
            "note": (
                "Meta ofrece webhooks de mensajes/comentarios, no del estado de "
                "publicación de un contenedor."
            ),
        },
        Platform.TIKTOK.value: {
            "publish_status_webhook": False,
            "strategy": "polling de /v2/post/publish/status/fetch/",
            "poll_interval_seconds": settings.processing_poll_interval_seconds,
        },
        Platform.YOUTUBE.value: {
            "publish_status_webhook": False,
            "strategy": "polling de videos.list (part=status,processingDetails)",
            "poll_interval_seconds": settings.processing_poll_interval_seconds,
            "note": (
                "PubSubHubbub notifica videos nuevos del canal, no el progreso "
                "de una subida concreta."
            ),
        },
    }
