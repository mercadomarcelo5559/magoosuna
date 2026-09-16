"""Cifrado simétrico de tokens OAuth y firma de URLs temporales.

Los tokens de acceso/refresh nunca se guardan en claro en la base de datos:
se cifran con Fernet (AES-128-CBC + HMAC-SHA256) usando `ENCRYPTION_KEY`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX: Final = "fernet:"


class CryptoError(RuntimeError):
    """Error de configuración o de descifrado."""


def generate_encryption_key() -> str:
    """Genera una clave Fernet válida (urlsafe base64 de 32 bytes)."""
    return Fernet.generate_key().decode()


def _derive_key(raw: str) -> bytes:
    """Acepta una clave Fernet directa o deriva una desde cualquier secreto.

    Derivar permite arrancar en desarrollo con un secreto arbitrario, pero la
    forma recomendada es generar una clave Fernet real.
    """
    candidate = raw.strip()
    try:
        decoded = base64.urlsafe_b64decode(candidate.encode())
        if len(decoded) == 32:
            return candidate.encode()
    except Exception:  # noqa: S110 - no es base64 válido: derivamos la clave abajo
        pass
    digest = hashlib.sha256(candidate.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    if not settings.encryption_key:
        raise CryptoError(
            "ENCRYPTION_KEY no está configurada. Genera una con: "
            "python -m app.security.crypto --generate-key"
        )
    return Fernet(_derive_key(settings.encryption_key))


def encrypt(value: str | None) -> str | None:
    """Cifra un secreto. Devuelve None si la entrada es None."""
    if value is None:
        return None
    token = _fernet().encrypt(value.encode()).decode()
    return f"{_PREFIX}{token}"


def decrypt(value: str | None) -> str | None:
    """Descifra un secreto previamente cifrado con :func:`encrypt`."""
    if value is None:
        return None
    if not value.startswith(_PREFIX):
        raise CryptoError("El valor almacenado no tiene el formato cifrado esperado")
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - depende de la clave
        raise CryptoError("No se pudo descifrar el token. ¿Cambió ENCRYPTION_KEY?") from exc


# --------------------------------------------------------------------- hashing
def hash_api_key(api_key: str) -> str:
    """Hash determinista (SHA-256 con pepper) para buscar API keys en la BD."""
    pepper = settings.signing_secret or settings.encryption_key
    return hashlib.sha256(f"{pepper}:{api_key}".encode()).hexdigest()


def generate_api_key(prefix: str = "svk") -> str:
    """Genera una API key opaca: `svk_<40 chars>`."""
    return f"{prefix}_{secrets.token_urlsafe(30)}"


def api_key_fingerprint(api_key: str) -> str:
    """Primeros caracteres de la key, seguros para logs y para mostrar en UI."""
    return api_key[:10]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ------------------------------------------------------------- firma de URLs
def _signing_key() -> bytes:
    secret = settings.signing_secret or settings.encryption_key
    if not secret:
        raise CryptoError("SIGNING_SECRET no está configurada")
    return secret.encode()


def sign_payload(payload: str, ttl_seconds: int) -> str:
    """Devuelve `<expira>.<firma>` para `payload`."""
    expires_at = int(time.time()) + ttl_seconds
    message = f"{payload}:{expires_at}".encode()
    signature = hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def verify_signature(payload: str, token: str) -> bool:
    """Verifica un token generado por :func:`sign_payload`."""
    try:
        expires_raw, signature = token.split(".", 1)
        expires_at = int(expires_raw)
    except (ValueError, AttributeError):
        return False
    if expires_at < int(time.time()):
        return False
    message = f"{payload}:{expires_at}".encode()
    expected = hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


if __name__ == "__main__":  # pragma: no cover - utilidad de línea de comandos
    import argparse

    parser = argparse.ArgumentParser(description="Utilidades de cifrado")
    parser.add_argument("--generate-key", action="store_true", help="Genera ENCRYPTION_KEY")
    parser.add_argument("--generate-secret", action="store_true", help="Genera SIGNING_SECRET")
    parser.add_argument("--generate-api-key", action="store_true", help="Genera una API key")
    args = parser.parse_args()

    if args.generate_key:
        print(generate_encryption_key())
    if args.generate_secret:
        print(secrets.token_urlsafe(48))
    if args.generate_api_key:
        print(generate_api_key())
    if not any(vars(args).values()):
        parser.print_help()
