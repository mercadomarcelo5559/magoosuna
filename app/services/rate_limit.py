"""Rate limiting por API key. Usa Redis si está disponible; si no, memoria."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_after: int


class _InMemoryLimiter:
    """Ventana fija en memoria. Suficiente para un solo proceso (dev)."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> RateLimitResult:
        now = time.time()
        with self._lock:
            count, window_start = self._buckets.get(key, (0, now))
            if now - window_start >= window:
                count, window_start = 0, now
            count += 1
            self._buckets[key] = (count, window_start)
            # Limpieza perezosa para no crecer sin límite.
            if len(self._buckets) > 10_000:
                cutoff = now - window
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] >= cutoff}
        reset_after = int(max(1, window - (now - window_start)))
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            reset_after=reset_after,
        )


class _RedisLimiter:
    """Ventana fija en Redis (INCR + EXPIRE). Válido con varios procesos."""

    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    def hit(self, key: str, limit: int, window: int) -> RateLimitResult:
        redis_key = f"ratelimit:{key}:{int(time.time() // window)}"
        pipeline = self._client.pipeline()
        pipeline.incr(redis_key, 1)
        pipeline.expire(redis_key, window + 1)
        count = int(pipeline.execute()[0])
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            reset_after=window - int(time.time() % window),
        )


_limiter: _RedisLimiter | _InMemoryLimiter | None = None
_fallback = _InMemoryLimiter()


def _get_limiter() -> _RedisLimiter | _InMemoryLimiter:
    global _limiter
    if _limiter is None:
        try:
            limiter = _RedisLimiter(settings.redis_url)
            limiter._client.ping()
            _limiter = limiter
            logger.info("rate limiting con Redis activo")
        except Exception as exc:
            logger.warning("Redis no disponible para rate limiting (%s); usando memoria", exc)
            _limiter = _fallback
    return _limiter


def check(
    identifier: str, *, limit: int | None = None, window: int | None = None
) -> RateLimitResult:
    """Consume una unidad de cuota para `identifier`."""
    effective_limit = limit or settings.rate_limit_requests
    effective_window = window or settings.rate_limit_window_seconds
    if not settings.rate_limit_enabled:
        return RateLimitResult(True, effective_limit, effective_limit, effective_window)
    try:
        return _get_limiter().hit(identifier, effective_limit, effective_window)
    except Exception as exc:
        logger.warning("rate limiting degradado a memoria: %s", exc)
        return _fallback.hit(identifier, effective_limit, effective_window)


def reset() -> None:
    """Reinicia el limiter (tests)."""
    global _limiter
    _limiter = None
    _fallback.__init__()  # type: ignore[misc]
