"""Conexión de cuentas sociales vía OAuth (Instagram, TikTok, YouTube)."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentAuth, DbSession
from app.logging_config import get_logger
from app.models import OAuthState, Platform, utcnow
from app.models.base import as_utc
from app.providers import get_provider
from app.providers.errors import ConfigurationError, ProviderError
from app.schemas import (
    AuthorizeResponse,
    ConnectManualRequest,
    OAuthCallbackResponse,
    SocialAccountResponse,
)
from app.security.crypto import decrypt, encrypt
from app.services import accounts as accounts_service

logger = get_logger(__name__)
router = APIRouter(prefix="/oauth", tags=["oauth"])

#: Validez del `state` de OAuth.
STATE_TTL = timedelta(minutes=10)


def _redirect_uri_for(platform: Platform) -> str:
    """Redirect URI configurada, o la derivada de `PUBLIC_BASE_URL`."""
    configured = {
        Platform.INSTAGRAM: settings.instagram_redirect_uri,
        Platform.TIKTOK: settings.tiktok_redirect_uri,
        Platform.YOUTUBE: settings.youtube_redirect_uri,
    }.get(platform, "")
    if configured:
        return configured
    return f"{settings.public_base_url}{settings.api_prefix}/oauth/{platform.value}/callback"


@router.get(
    "/{platform}/authorize",
    response_model=AuthorizeResponse,
    summary="Paso 1: obtener la URL de autorización",
)
def authorize(
    platform: Platform,
    auth: CurrentAuth,
    db: DbSession,
    return_url: str | None = Query(
        default=None,
        description="URL de tu app (Macaly) a la que volver al terminar el OAuth",
    ),
    redirect: bool = Query(
        default=False,
        description="Si es true responde con un 307 al diálogo en lugar de JSON",
    ),
) -> AuthorizeResponse | RedirectResponse:
    """Genera la URL del diálogo de consentimiento de la plataforma.

    Macaly abre esa URL en el navegador del usuario. Al aceptar, la plataforma
    llama a `/oauth/{platform}/callback` y la cuenta queda conectada.
    """
    provider = get_provider(platform)
    redirect_uri = _redirect_uri_for(platform)

    try:
        state_value = secrets.token_urlsafe(32)
        request_data = provider.build_authorization_request(
            state=state_value, redirect_uri=redirect_uri
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc

    db.add(
        OAuthState(
            state=request_data.state,
            platform=platform,
            client_id=auth.client_id,
            redirect_uri=redirect_uri,
            return_url=return_url,
            code_verifier_encrypted=encrypt(request_data.code_verifier),
            extra=request_data.extra,
            expires_at=utcnow() + STATE_TTL,
        )
    )
    db.commit()

    logger.info("oauth: autorización iniciada platform=%s client_id=%s", platform, auth.client_id)

    if redirect:
        return RedirectResponse(
            url=request_data.url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )
    return AuthorizeResponse(
        platform=platform,
        authorization_url=request_data.url,
        state=request_data.state,
        expires_in=int(STATE_TTL.total_seconds()),
    )


def _callback_html(title: str, message: str, *, ok: bool) -> str:
    color = "#16a34a" if ok else "#dc2626"
    icon = "✓" if ok else "✕"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 background:#0b0f14;color:#e5e7eb;display:flex;align-items:center;
 justify-content:center;min-height:100vh;margin:0;padding:24px}}
 .card{{background:#11161d;border:1px solid #1f2937;border-radius:16px;
 padding:32px;max-width:420px;text-align:center}}
 .icon{{font-size:44px;color:{color};line-height:1}}
 h1{{font-size:19px;margin:16px 0 8px}} p{{color:#9ca3af;font-size:14px;line-height:1.6;margin:0}}
</style></head>
<body><div class="card"><div class="icon">{icon}</div>
<h1>{title}</h1><p>{message}</p></div></body></html>"""


@router.get(
    "/{platform}/callback",
    summary="Paso 2: callback de la plataforma (no la llames tú)",
    response_model=None,
)
def callback(
    platform: Platform,
    db: DbSession,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> HTMLResponse | RedirectResponse:
    """Recibe el `code`, lo canjea por tokens y guarda la cuenta cifrada.

    Este endpoint NO requiere API key: lo invoca el navegador del usuario tras
    aceptar en la plataforma. La seguridad la aporta el `state` de un solo uso.
    """
    if error:
        logger.warning("oauth: la plataforma %s devolvió error=%s", platform, error)
        return HTMLResponse(
            _callback_html(
                "No se pudo conectar la cuenta",
                f"{platform.value}: {error_description or error}",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not code or not state:
        return HTMLResponse(
            _callback_html(
                "Callback incompleto",
                "Faltan los parámetros `code` y/o `state`.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    record = db.scalars(select(OAuthState).where(OAuthState.state == state)).first()
    if record is None or record.platform != platform:
        return HTMLResponse(
            _callback_html(
                "Estado inválido",
                "El `state` no existe o no corresponde a esta plataforma. "
                "Vuelve a iniciar la conexión.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    expires_at = as_utc(record.expires_at)
    if record.used_at is not None or (expires_at and expires_at <= utcnow()):
        return HTMLResponse(
            _callback_html(
                "Enlace caducado",
                "Este enlace de autorización ya se usó o caducó. Inicia el proceso de nuevo.",
                ok=False,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # El state es de un solo uso: lo marcamos antes de canjear el code.
    record.used_at = utcnow()
    db.add(record)
    db.commit()

    provider = get_provider(platform)
    try:
        credentials = provider.exchange_code(
            code=code,
            redirect_uri=record.redirect_uri,
            code_verifier=decrypt(record.code_verifier_encrypted),
        )
        info = provider.get_account(credentials)
        account = accounts_service.upsert_account(
            db,
            client_id=record.client_id,
            platform=platform,
            external_account_id=info.external_account_id,
            account_name=info.account_name,
            credentials=credentials,
            metadata=info.metadata,
        )
    except ProviderError as exc:
        logger.error("oauth: fallo conectando %s: %s", platform, exc)
        return HTMLResponse(
            _callback_html("No se pudo conectar la cuenta", str(exc), ok=False),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    logger.info(
        "oauth: cuenta conectada platform=%s account_id=%s client_id=%s",
        platform,
        account.id,
        record.client_id,
    )

    if record.return_url:
        separator = "&" if "?" in record.return_url else "?"
        url = (
            f"{record.return_url}{separator}"
            f"status=connected&platform={platform.value}&account_id={account.id}"
        )
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    return HTMLResponse(
        _callback_html(
            "Cuenta conectada",
            f"{platform.value}: {account.account_name}. Ya puedes cerrar esta ventana "
            "y volver a la aplicación.",
            ok=True,
        )
    )


@router.post(
    "/connect",
    response_model=OAuthCallbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Conectar una cuenta con un token ya obtenido (avanzado)",
)
def connect_manual(
    payload: ConnectManualRequest, auth: CurrentAuth, db: DbSession
) -> OAuthCallbackResponse:
    """Registra una cuenta a partir de un access token existente.

    Útil para tokens de larga duración generados en el portal de la plataforma
    o para pruebas. El token se cifra igual que en el flujo OAuth completo.
    """
    from app.providers import OAuthCredentials

    provider = get_provider(payload.platform)
    credentials = OAuthCredentials(
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        expires_at=(
            utcnow() + timedelta(seconds=payload.expires_in_seconds)
            if payload.expires_in_seconds
            else None
        ),
        scopes=payload.scopes,
        metadata=dict(payload.metadata),
    )

    external_id = payload.external_account_id
    account_name = payload.account_name
    metadata = dict(payload.metadata)
    if not external_id or not account_name:
        try:
            info = provider.get_account(credentials)
            external_id = external_id or info.external_account_id
            account_name = account_name or info.account_name
            metadata.update(info.metadata)
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo validar el token con {payload.platform.value}: {exc}",
            ) from exc

    account = accounts_service.upsert_account(
        db,
        client_id=auth.client_id,
        platform=payload.platform,
        external_account_id=str(external_id),
        account_name=str(account_name),
        credentials=credentials,
        metadata=metadata,
    )
    return OAuthCallbackResponse(
        platform=payload.platform,
        account=SocialAccountResponse.from_account(account),
        message="Cuenta conectada correctamente",
    )
