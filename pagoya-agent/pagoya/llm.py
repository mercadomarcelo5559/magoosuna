"""Cliente de Claude compartido."""
from __future__ import annotations

import json
import logging
import re

import anthropic

from .config import env

log = logging.getLogger(__name__)
_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY") or None)
    return _client


def model() -> str:
    return env("CLAUDE_MODEL", "claude-opus-5-5")


def create(**kw):
    """messages.create con fallback automático del servidor ante rechazos."""
    kw.setdefault("model", model())
    kw.setdefault("output_config", {"effort": env("CLAUDE_EFFORT", "low")})
    return client().beta.messages.create(
        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def ask(system: str, prompt: str, max_tokens: int = 16000, effort: str = "medium") -> str:
    with client().beta.messages.stream(
        model=model(), max_tokens=max_tokens, system=system,
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        resp = stream.get_final_message()
    return text_of(resp)


def ask_json(system: str, prompt: str, max_tokens: int = 32000, effort: str = "medium"):
    """Pide JSON y lo parsea (tolerante a ```json ...```)."""
    raw = ask(system + "\n\nResponde SOLO con JSON válido, sin texto adicional.", prompt,
              max_tokens=max_tokens, effort=effort)
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    raw = m.group(1) if m else raw
    start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0], default=0)
    return json.loads(raw[start:])
