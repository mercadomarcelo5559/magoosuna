"""Gestión de cuentas sociales: credenciales, refresh automático, desconexión."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import Platform, SocialAccount, as_utc, utcnow
from app.providers import OAuthCredentials, get_provider
from app.providers.errors import AuthenticationError, ProviderError
from app.security.crypto import decrypt, encrypt

logger = get_logger(__name__)

#: Margen antes de la caducidad para renovar el token proactivamente.
REFRESH_MARGIN = timedelta(minutes=10)


class AccountNotFoundError(LookupError):
    def __init__(self, message: str = "Cuenta social no encontrada") -> None:
        super().__init__(message)


def credentials_from_account(account: SocialAccount) -> OAuthCredentials:
    """Descifra los tokens y los envuelve en `OAuthCredentials`."""
    access_token = decrypt(account.access_token_encrypted)
    if not access_token:
        raise AuthenticationError("La cuenta no tiene access token almacenado")
    metadata = dict(account.account_metadata or {})
    metadata.setdefault("external_account_id", account.external_account_id)
    return OAuthCredentials(
        access_token=access_token,
        refresh_token=decrypt(account.refresh_token_encrypted),
        expires_at=as_utc(account.token_expiration),
        refresh_expires_at=as_utc(account.refresh_token_expiration),
        scopes=list(account.scopes or []),
        metadata=metadata,
    )


def apply_credentials(account: SocialAccount, credentials: OAuthCredentials) -> None:
    """Guarda (cifrados) los tokens nuevos en la cuenta."""
    account.access_token_encrypted = encrypt(credentials.access_token) or ""
    if credentials.refresh_token:
        account.refresh_token_encrypted = encrypt(credentials.refresh_token)
    account.token_expiration = credentials.expires_at
    if credentials.refresh_expires_at:
        account.refresh_token_expiration = credentials.refresh_expires_at
    if credentials.scopes:
        account.scopes = credentials.scopes
    merged = dict(account.account_metadata or {})
    merged.update({k: v for k, v in credentials.metadata.items() if v is not None})
    account.account_metadata = merged
    account.last_refreshed_at = utcnow()
    account.last_error = None


def get_account(db: Session, client_id: str, account_id: str) -> SocialAccount:
    account = db.scalars(
        select(SocialAccount).where(
            SocialAccount.id == account_id, SocialAccount.client_id == client_id
        )
    ).first()
    if account is None:
        raise AccountNotFoundError(f"No existe la cuenta {account_id}")
    return account


def find_active_account(
    db: Session, client_id: str, platform: Platform, account_id: str | None = None
) -> SocialAccount:
    """Localiza la cuenta activa a usar para publicar en `platform`."""
    query = select(SocialAccount).where(
        SocialAccount.client_id == client_id,
        SocialAccount.platform == platform,
        SocialAccount.is_active.is_(True),
    )
    if account_id:
        query = query.where(SocialAccount.id == account_id)
    accounts = list(db.scalars(query.order_by(SocialAccount.created_at.desc())))
    if not accounts:
        raise AccountNotFoundError(
            f"No hay ninguna cuenta de {platform.value} conectada"
            + (f" con id {account_id}" if account_id else "")
            + f". Conéctala con GET /v1/oauth/{platform.value}/authorize"
        )
    return accounts[0]


def ensure_fresh_credentials(
    db: Session, account: SocialAccount, *, force: bool = False
) -> OAuthCredentials:
    """Devuelve credenciales válidas, renovándolas si están por caducar.

    Se usa antes de cada publicación y en la tarea periódica de refresco.
    """
    credentials = credentials_from_account(account)
    needs_refresh = force or account.token_expires_within(REFRESH_MARGIN)
    if not needs_refresh:
        return credentials

    provider = get_provider(account.platform)
    try:
        refreshed = provider.refresh_token(credentials)
    except AuthenticationError:
        account.last_error = "El token caducó y no se pudo renovar. Reconecta la cuenta."
        account.is_active = False
        db.add(account)
        db.commit()
        raise
    except ProviderError as exc:
        # Un fallo temporal no debe invalidar la cuenta: seguimos con el token
        # actual y que el reintento lo resuelva.
        logger.warning(
            "No se pudo renovar el token de %s (%s): %s",
            account.platform,
            account.id,
            exc,
        )
        return credentials

    apply_credentials(account, refreshed)
    db.add(account)
    db.commit()
    db.refresh(account)
    logger.info(
        "Token renovado platform=%s account_id=%s expira=%s",
        account.platform,
        account.id,
        refreshed.expires_at,
    )
    return credentials_from_account(account)


def disconnect_account(db: Session, account: SocialAccount, *, revoke: bool = True) -> None:
    """Desactiva la cuenta, revoca en la plataforma y borra los tokens."""
    if revoke:
        try:
            provider = get_provider(account.platform)
            provider.revoke(credentials_from_account(account))
        except (ProviderError, ValueError) as exc:
            logger.warning("Revocación remota fallida para %s: %s", account.id, exc)

    account.is_active = False
    account.disconnected_at = utcnow()
    # No conservamos tokens de cuentas desconectadas.
    account.access_token_encrypted = encrypt("") or ""
    account.refresh_token_encrypted = None
    account.token_expiration = None
    account.refresh_token_expiration = None
    db.add(account)
    db.commit()
    logger.info("Cuenta desconectada platform=%s account_id=%s", account.platform, account.id)


def upsert_account(
    db: Session,
    *,
    client_id: str,
    platform: Platform,
    external_account_id: str,
    account_name: str,
    credentials: OAuthCredentials,
    metadata: dict | None = None,
) -> SocialAccount:
    """Crea o reactiva la cuenta y guarda los tokens cifrados."""
    account = db.scalars(
        select(SocialAccount).where(
            SocialAccount.client_id == client_id,
            SocialAccount.platform == platform,
            SocialAccount.external_account_id == external_account_id,
        )
    ).first()

    if account is None:
        account = SocialAccount(
            client_id=client_id,
            platform=platform,
            external_account_id=external_account_id,
            account_name=account_name,
            access_token_encrypted="",
            scopes=[],
            account_metadata={},
        )

    account.account_name = account_name
    account.is_active = True
    account.disconnected_at = None
    if metadata:
        credentials.metadata.update(metadata)
    credentials.metadata["external_account_id"] = external_account_id
    apply_credentials(account, credentials)

    db.add(account)
    db.commit()
    db.refresh(account)
    return account
