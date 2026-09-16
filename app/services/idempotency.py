"""Idempotencia: `Idempotency-Key` evita publicaciones duplicadas."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import IdempotencyRecord

logger = get_logger(__name__)


class IdempotencyConflictError(RuntimeError):
    """La misma clave se reutilizó con un cuerpo distinto."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"La Idempotency-Key '{key}' ya se usó con un cuerpo diferente. "
            "Usa una clave nueva para una solicitud distinta."
        )
        self.key = key


class IdempotencyInProgressError(RuntimeError):
    """La solicitud original aún se está procesando."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Ya hay una solicitud en curso con la Idempotency-Key '{key}'. "
            "Reintenta en unos segundos."
        )
        self.key = key


def hash_request(payload: Any) -> str:
    """Hash estable del cuerpo de la petición (orden de claves normalizado)."""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def begin(
    db: Session, *, client_id: str, key: str, endpoint: str, payload: Any
) -> IdempotencyRecord | None:
    """Reserva la clave. Devuelve el registro previo si ya existe respuesta.

    - Si la clave es nueva: crea el registro (sin respuesta) y devuelve None.
    - Si existe con la misma huella y ya tiene respuesta: la devuelve (replay).
    - Si existe con la misma huella pero sin respuesta: `IdempotencyInProgressError`.
    - Si existe con huella distinta: `IdempotencyConflictError`.
    """
    request_hash = hash_request(payload)
    existing = db.scalars(
        select(IdempotencyRecord).where(
            IdempotencyRecord.client_id == client_id, IdempotencyRecord.key == key
        )
    ).first()

    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(key)
        if existing.response_body is None:
            raise IdempotencyInProgressError(key)
        logger.info("idempotencia: replay key=%s endpoint=%s", key, endpoint)
        return existing

    record = IdempotencyRecord(
        client_id=client_id, key=key, endpoint=endpoint, request_hash=request_hash
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Carrera: otro request reservó la clave un instante antes.
        db.rollback()
        concurrent = db.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.client_id == client_id, IdempotencyRecord.key == key
            )
        ).first()
        if concurrent is None:
            raise
        if concurrent.request_hash != request_hash:
            raise IdempotencyConflictError(key) from None
        if concurrent.response_body is None:
            raise IdempotencyInProgressError(key) from None
        return concurrent
    return None


def complete(
    db: Session,
    *,
    client_id: str,
    key: str,
    response_body: dict[str, Any],
    resource_id: str | None = None,
    status_code: int = 201,
) -> None:
    """Guarda la respuesta para servir replays idénticos."""
    record = db.scalars(
        select(IdempotencyRecord).where(
            IdempotencyRecord.client_id == client_id, IdempotencyRecord.key == key
        )
    ).first()
    if record is None:
        return
    record.response_body = response_body
    record.resource_id = resource_id
    record.response_status = status_code
    db.add(record)
    db.commit()


def release(db: Session, *, client_id: str, key: str) -> None:
    """Libera una clave reservada cuando la operación falló.

    Así el cliente puede reintentar con la misma clave.
    """
    record = db.scalars(
        select(IdempotencyRecord).where(
            IdempotencyRecord.client_id == client_id,
            IdempotencyRecord.key == key,
            IdempotencyRecord.response_body.is_(None),
        )
    ).first()
    if record is not None:
        db.delete(record)
        db.commit()
