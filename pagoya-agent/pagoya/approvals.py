"""Links firmados para aprobar / rechazar desde el correo."""
from __future__ import annotations

import hashlib
import hmac

from .config import env, public_url


def sign(*parts) -> str:
    msg = ":".join(str(p) for p in parts).encode()
    return hmac.new(env("SECRET_KEY", "dev-secret").encode(), msg, hashlib.sha256).hexdigest()[:32]


def check(token: str, *parts) -> bool:
    return hmac.compare_digest(token or "", sign(*parts))


def link(path: str, *parts) -> str:
    return public_url(f"{path}?t={sign(path, *parts)}")


def admin_token() -> str:
    return sign("admin")
