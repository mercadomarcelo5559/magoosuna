"""Bucle de polling controlado, compartido por todos los providers.

Evita duplicar la lógica de espera en Instagram, TikTok y YouTube, y garantiza
que el polling no sea agresivo (requisito 16): un intervalo mínimo por consulta
y una espera que nunca sobrepasa el plazo restante.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

#: Intervalo mínimo entre consultas de estado, en segundos. Ninguna
#: configuración puede bajar de aquí para no castigar las APIs externas.
MIN_POLL_INTERVAL_SECONDS = 5


def poll_ticks(*, timeout_seconds: float, interval_seconds: float) -> Iterator[int]:
    """Itera los "turnos" de consulta hasta agotar `timeout_seconds`.

    Consulta inmediatamente (turno 0) y después espera `interval_seconds`
    entre turnos, sin dormir más de lo que queda de plazo. Cuando el plazo se
    agota el iterador termina, de modo que quien lo usa puede lanzar su propio
    error de timeout con el último estado conocido.
    """
    interval = max(float(interval_seconds), MIN_POLL_INTERVAL_SECONDS)
    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
    attempt = 0
    while True:
        yield attempt
        attempt += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(interval, remaining))
        if time.monotonic() >= deadline:
            return
