"""Google Business Profile: publicación semanal y respuestas a reseñas."""
from __future__ import annotations

import html
import logging

import httpx


from . import llm, mailer
from .approvals import link
from .config import env
from .content import CAL_SYSTEM
from .db import Approval, kv_get, kv_set, session

log = logging.getLogger(__name__)
V4 = "https://mybusiness.googleapis.com/v4"
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def configured() -> bool:
    return all(env(k) for k in ("GBP_ACCOUNT_ID", "GBP_LOCATION_ID", "GOOGLE_OAUTH_CLIENT_ID",
                                "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"))


def _token() -> str:
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": env("GOOGLE_OAUTH_CLIENT_ID"), "client_secret": env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_OAUTH_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]


def _loc() -> str:
    return f"accounts/{env('GBP_ACCOUNT_ID')}/locations/{env('GBP_LOCATION_ID')}"


def weekly_post() -> str:
    if not configured():
        return "GBP no configurado"
    text = llm.ask(CAL_SYSTEM, "Escribe una publicación para el perfil de Google de Pagoya (máx 1,200 caracteres, "
                               "sin hashtags, sin emojis excesivos). Alterna entre tip de cobranza, función de la "
                               "app o la configuración gratis. Termina invitando a agendar una demo.",
                   max_tokens=4000, effort="low")
    r = httpx.post(f"{V4}/{_loc()}/localPosts", timeout=30, headers={"Authorization": f"Bearer {_token()}"},
                   json={"languageCode": "es-MX", "summary": text[:1500], "topicType": "STANDARD",
                         "callToAction": {"actionType": "LEARN_MORE", "url": env("SITE_URL")}})
    r.raise_for_status()
    return r.json().get("name", "")


def review_reply_text(name: str, stars: int, comment: str) -> str:
    return llm.ask(
        "Respondes reseñas de Google de Pagoya (software de cobranza para academias). Español de México, "
        "breve (2-3 frases), cálido y profesional. Si la reseña es negativa, reconoce, ofrece resolver por "
        "WhatsApp o correo, sin discutir ni dar datos internos.",
        f"Reseña de {name} ({stars} estrellas): «{comment}»", max_tokens=2000, effort="low")


def put_reply(review_name: str, text: str) -> None:
    r = httpx.put(f"{V4}/{review_name}/reply", timeout=30, headers={"Authorization": f"Bearer {_token()}"},
                  json={"comment": text})
    r.raise_for_status()


def check_reviews() -> dict:
    """4-5 estrellas: responde solo. 1-3: te manda borrador para aprobar."""
    if not configured():
        return {"skipped": "GBP no configurado"}
    r = httpx.get(f"{V4}/{_loc()}/reviews", timeout=30, headers={"Authorization": f"Bearer {_token()}"})
    r.raise_for_status()
    out = {"auto": 0, "pending": 0}
    with session() as s:
        seen = set(kv_get(s, "gbp_seen_reviews", []))
        for rv in r.json().get("reviews", []):
            if rv.get("reviewReply") or rv["name"] in seen:
                continue
            seen.add(rv["name"])
            stars = STARS.get(rv.get("starRating"), 3)
            who = rv.get("reviewer", {}).get("displayName", "")
            text = review_reply_text(who, stars, rv.get("comment", ""))
            if stars >= 4:
                put_reply(rv["name"], text)
                out["auto"] += 1
            else:
                ap = Approval(kind="review_reply", ref=rv["name"], payload={"text": text})
                s.add(ap)
                s.flush()
                mailer.send_owner(
                    f"[Pagoya] Reseña de {stars}★ en Google — revisa la respuesta",
                    f"<p><b>{html.escape(who)}</b>: «{html.escape(rv.get('comment', ''))}»</p>"
                    f"<p>Respuesta propuesta:</p><blockquote>{html.escape(text)}</blockquote>"
                    f"<p><a href='{link(f'/approve/review_reply/{ap.id}', 'review_reply', ap.id)}'>✅ Publicar</a> | "
                    f"<a href='{link(f'/changes/review_reply/{ap.id}', 'review_reply', ap.id)}'>✏️ Editar</a></p>")
                out["pending"] += 1
        kv_set(s, "gbp_seen_reviews", sorted(seen)[-500:])
    return out


def approve_reply(approval_id: int, text: str | None = None) -> None:
    with session() as s:
        ap = s.get(Approval, approval_id)
        put_reply(ap.ref, text or ap.payload["text"])
        ap.status = "approved"



