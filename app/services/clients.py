"""Alta de clientes y gestión/rotación de API keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import ApiKey, Client, as_utc, utcnow
from app.security.crypto import api_key_fingerprint, generate_api_key, hash_api_key

logger = get_logger(__name__)

BOOTSTRAP_CLIENT_NAME = "bootstrap"


@dataclass(slots=True)
class IssuedApiKey:
    """La key en claro sólo existe en este objeto, una única vez."""

    api_key: str
    record: ApiKey


def create_client(db: Session, *, name: str, email: str | None = None) -> Client:
    client = Client(name=name, email=email)
    db.add(client)
    db.commit()
    db.refresh(client)
    logger.info("clients: cliente creado client_id=%s name=%s", client.id, name)
    return client


def issue_api_key(
    db: Session,
    client: Client,
    *,
    label: str = "default",
    expires_at: datetime | None = None,
    raw_key: str | None = None,
) -> IssuedApiKey:
    """Genera una API key nueva. El valor en claro no se persiste."""
    api_key = raw_key or generate_api_key()
    record = ApiKey(
        client_id=client.id,
        label=label,
        key_hash=hash_api_key(api_key),
        key_prefix=api_key_fingerprint(api_key),
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "clients: API key emitida client_id=%s prefix=%s label=%s",
        client.id,
        record.key_prefix,
        label,
    )
    return IssuedApiKey(api_key=api_key, record=record)


def revoke_api_key(db: Session, record: ApiKey) -> None:
    record.is_active = False
    record.revoked_at = utcnow()
    db.add(record)
    db.commit()
    logger.info("clients: API key revocada prefix=%s", record.key_prefix)


def rotate_api_key(
    db: Session, client: Client, *, old: ApiKey | None = None, label: str = "rotated"
) -> IssuedApiKey:
    """Emite una key nueva y revoca la anterior (rotación del punto 17)."""
    issued = issue_api_key(db, client, label=label)
    if old is not None:
        revoke_api_key(db, old)
    return issued


def resolve_api_key(db: Session, api_key: str) -> ApiKey | None:
    """Busca la API key por su hash y valida estado/caducidad."""
    if not api_key:
        return None
    record = db.scalars(select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key))).first()
    if record is None or not record.is_active:
        return None
    expires = as_utc(record.expires_at)
    if expires is not None and expires <= utcnow():
        return None
    if not record.client.is_active:
        return None
    return record


def touch_api_key(db: Session, record: ApiKey) -> None:
    """Marca el último uso (útil para auditoría). Tolera fallos."""
    try:
        record.last_used_at = utcnow()
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()


def list_api_keys(db: Session, client_id: str) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey).where(ApiKey.client_id == client_id).order_by(ApiKey.created_at.desc())
        )
    )


def ensure_bootstrap_keys(db: Session) -> None:
    """Registra las API keys de `BOOTSTRAP_API_KEYS` si aún no existen.

    Permite arrancar en desarrollo con una key conocida sin llamar al endpoint
    de administración. En producción se deja vacío y se usan claves generadas.
    """
    raw_keys = settings.bootstrap_api_key_list
    if not raw_keys:
        return

    client = db.scalars(select(Client).where(Client.name == BOOTSTRAP_CLIENT_NAME)).first()
    if client is None:
        client = create_client(db, name=BOOTSTRAP_CLIENT_NAME)

    for raw in raw_keys:
        existing = db.scalars(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw))).first()
        if existing is not None:
            continue
        issue_api_key(db, client, label="bootstrap", raw_key=raw)
        logger.info("clients: bootstrap API key registrada prefix=%s", api_key_fingerprint(raw))
