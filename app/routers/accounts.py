"""Gestión de cuentas sociales conectadas."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.deps import CurrentAuth, DbSession, PaginationDep
from app.logging_config import get_logger
from app.models import Platform, SocialAccount
from app.providers import get_provider
from app.providers.errors import ProviderError
from app.providers.instagram import InstagramProvider
from app.providers.tiktok import TikTokProvider
from app.schemas import (
    CreatorInfoResponse,
    MessageResponse,
    PaginatedResponse,
    PublishingLimitResponse,
    RefreshResponse,
    SocialAccountResponse,
)
from app.services import accounts as accounts_service
from app.services.accounts import AccountNotFoundError

logger = get_logger(__name__)
router = APIRouter(prefix="/accounts", tags=["cuentas"])


@router.get(
    "",
    response_model=PaginatedResponse[SocialAccountResponse],
    summary="Listar cuentas conectadas",
)
def list_accounts(
    auth: CurrentAuth,
    db: DbSession,
    page: PaginationDep,
    platform: Platform | None = Query(default=None),
    active_only: bool = Query(default=True),
) -> PaginatedResponse[SocialAccountResponse]:
    query = select(SocialAccount).where(SocialAccount.client_id == auth.client_id)
    if platform:
        query = query.where(SocialAccount.platform == platform)
    if active_only:
        query = query.where(SocialAccount.is_active.is_(True))

    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(
            query.order_by(SocialAccount.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    )
    return PaginatedResponse[SocialAccountResponse](
        items=[SocialAccountResponse.from_account(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def _get_account(db, client_id: str, account_id: str) -> SocialAccount:
    try:
        return accounts_service.get_account(db, client_id, account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{account_id}",
    response_model=SocialAccountResponse,
    summary="Detalle de una cuenta",
)
def get_account(account_id: str, auth: CurrentAuth, db: DbSession) -> SocialAccountResponse:
    account = _get_account(db, auth.client_id, account_id)
    return SocialAccountResponse.from_account(account)


@router.post(
    "/{account_id}/refresh",
    response_model=RefreshResponse,
    summary="Forzar la renovación del token",
)
def refresh_account(account_id: str, auth: CurrentAuth, db: DbSession) -> RefreshResponse:
    """Renueva el access token de la cuenta llamando a la plataforma."""
    account = _get_account(db, auth.client_id, account_id)
    previous = account.token_expiration
    try:
        accounts_service.ensure_fresh_credentials(db, account, force=True)
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.refresh(account)
    refreshed = account.token_expiration != previous
    return RefreshResponse(
        account=SocialAccountResponse.from_account(account),
        refreshed=refreshed,
        message=(
            "Token renovado"
            if refreshed
            else "La plataforma no cambió la fecha de caducidad del token"
        ),
    )


@router.delete(
    "/{account_id}",
    response_model=MessageResponse,
    summary="Desconectar una cuenta",
)
def disconnect_account(
    account_id: str,
    auth: CurrentAuth,
    db: DbSession,
    revoke: bool = Query(default=True, description="Revocar además el token en la plataforma"),
) -> MessageResponse:
    """Desactiva la cuenta y borra sus tokens de nuestra base de datos."""
    account = _get_account(db, auth.client_id, account_id)
    accounts_service.disconnect_account(db, account, revoke=revoke)
    return MessageResponse(
        message=f"Cuenta {account.platform} '{account.account_name}' desconectada"
    )


@router.get(
    "/{account_id}/creator-info",
    response_model=CreatorInfoResponse,
    summary="TikTok: información del creador (privacidad y límites)",
)
def creator_info(account_id: str, auth: CurrentAuth, db: DbSession) -> CreatorInfoResponse:
    """Devuelve `creator_info` de TikTok, obligatorio antes de publicar.

    Incluye las opciones de privacidad permitidas y la duración máxima.
    """
    account = _get_account(db, auth.client_id, account_id)
    if Platform(account.platform) != Platform.TIKTOK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este endpoint sólo aplica a cuentas de TikTok",
        )
    provider = get_provider(Platform.TIKTOK)
    assert isinstance(provider, TikTokProvider)
    credentials = accounts_service.ensure_fresh_credentials(db, account)
    try:
        data = provider.get_creator_info(credentials)
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CreatorInfoResponse(data=data)


@router.get(
    "/{account_id}/publishing-limit",
    response_model=PublishingLimitResponse,
    summary="Instagram: cuota de publicación de las últimas 24 h",
)
def publishing_limit(account_id: str, auth: CurrentAuth, db: DbSession) -> PublishingLimitResponse:
    """Consulta `content_publishing_limit` (máximo 100 posts/24 h)."""
    account = _get_account(db, auth.client_id, account_id)
    if Platform(account.platform) != Platform.INSTAGRAM:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este endpoint sólo aplica a cuentas de Instagram",
        )
    provider = get_provider(Platform.INSTAGRAM)
    assert isinstance(provider, InstagramProvider)
    credentials = accounts_service.ensure_fresh_credentials(db, account)
    try:
        data = provider.get_publishing_limit(credentials, account.external_account_id)
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PublishingLimitResponse(
        quota_usage=data.get("quota_usage"), config=data.get("config"), raw=data
    )
