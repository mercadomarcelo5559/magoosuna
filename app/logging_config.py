"""Configuración de logging. Nunca registra tokens ni secretos."""

from __future__ import annotations

import logging
import logging.config
import re
from typing import Any

from app.config import settings

#: Patrones que se redactan de cualquier mensaje antes de escribirlo.
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(access_token=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(refresh_token=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(client_secret=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(code=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(\"access_token\"\s*:\s*\")[^\"]+", re.IGNORECASE),
    re.compile(r"(\"refresh_token\"\s*:\s*\")[^\"]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(OAuth\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"(fernet:)[A-Za-z0-9\-_=]+"),
)

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "authorization",
    "encryption_key",
    "signing_secret",
    "code",
    "code_verifier",
    "password",
}


def redact(text: str) -> str:
    """Sustituye secretos conocidos por `***`."""
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Versión segura de un diccionario, apta para logs."""
    safe: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            safe[key] = "***"
        elif isinstance(value, dict):
            safe[key] = redact_mapping(value)
        else:
            safe[key] = value
    return safe


class RedactingFilter(logging.Filter):
    """Filtro que redacta secretos del mensaje final."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging() -> None:
    """Configura el logging raíz de la aplicación (idempotente)."""
    if settings.log_json:
        formatter: dict[str, Any] = {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    else:
        formatter = {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        }

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"redact": {"()": RedactingFilter}},
            "formatters": {"default": formatter},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["redact"],
                }
            },
            "root": {"handlers": ["console"], "level": settings.log_level.upper()},
            "loggers": {
                "uvicorn.access": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "sqlalchemy.engine": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
