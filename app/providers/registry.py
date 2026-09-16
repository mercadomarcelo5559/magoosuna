"""Registro de providers. Punto único para añadir plataformas nuevas."""

from __future__ import annotations

import functools

from app.models.enums import Platform
from app.providers.base import BaseProvider
from app.providers.instagram import InstagramProvider
from app.providers.tiktok import TikTokProvider
from app.providers.youtube import YouTubeProvider

#: Para añadir Facebook / X / LinkedIn: implementa BaseProvider y añádelo aquí.
_PROVIDER_CLASSES: dict[Platform, type[BaseProvider]] = {
    Platform.INSTAGRAM: InstagramProvider,
    Platform.TIKTOK: TikTokProvider,
    Platform.YOUTUBE: YouTubeProvider,
}


class UnsupportedPlatformError(ValueError):
    def __init__(self, platform: str) -> None:
        super().__init__(
            f"Plataforma '{platform}' no soportada. Disponibles: "
            f"{', '.join(sorted(p.value for p in _PROVIDER_CLASSES))}"
        )
        self.platform = platform


@functools.cache
def get_provider(platform: Platform | str) -> BaseProvider:
    """Devuelve la instancia (cacheada) del provider de una plataforma."""
    try:
        key = Platform(platform)
    except ValueError as exc:
        raise UnsupportedPlatformError(str(platform)) from exc
    provider_class = _PROVIDER_CLASSES.get(key)
    if provider_class is None:
        raise UnsupportedPlatformError(str(platform))
    return provider_class()


def supported_platforms() -> list[Platform]:
    return sorted(_PROVIDER_CLASSES, key=lambda p: p.value)


def platform_status() -> list[dict[str, object]]:
    """Resumen para `GET /v1/platforms`: qué está configurado y qué falta."""
    rows: list[dict[str, object]] = []
    for platform in supported_platforms():
        provider = get_provider(platform)
        rows.append(
            {
                "platform": platform.value,
                "configured": provider.is_configured(),
                "requires_public_video_url": provider.requires_public_url(),
                "docs_url": provider.setup_docs_url,
            }
        )
    return rows
