"""Instagram y Facebook vía Graph API oficial: publicar, DMs, comentarios y métricas."""
from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy import select

from . import bot, llm, notify
from .config import env, graph_version
from .db import Message, Prospect, find_prospect, session

log = logging.getLogger(__name__)


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{graph_version()}/{path}"


def _tok() -> dict:
    return {"access_token": env("META_PAGE_TOKEN")}


def configured() -> bool:
    return bool(env("META_PAGE_TOKEN") and env("META_PAGE_ID"))


def _post(path: str, data: dict) -> dict:
    r = httpx.post(_url(path), data={**data, **_tok()}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph {path}: {r.text[:400]}")
    return r.json()


def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(_url(path), params={**(params or {}), **_tok()}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph {path}: {r.text[:400]}")
    return r.json()


# ---------------- Publicación ----------------

def _ig_wait(container_id: str, tries: int = 40) -> None:
    for _ in range(tries):
        st = _get(container_id, {"fields": "status_code"}).get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar el video ({st})")
        time.sleep(10)
    raise RuntimeError("Instagram tardó demasiado en procesar el video")


def publish_instagram(kind: str, media_url: str, caption: str = "") -> str:
    ig = env("META_IG_USER_ID")
    data: dict = {"caption": caption} if kind != "story" else {}
    is_video = media_url.lower().endswith((".mp4", ".mov"))
    if kind == "reel":
        data.update(media_type="REELS", video_url=media_url, share_to_feed="true")
    elif kind == "story":
        data.update(media_type="STORIES", **({"video_url": media_url} if is_video else {"image_url": media_url}))
    else:
        data["image_url"] = media_url
    cid = _post(f"{ig}/media", data)["id"]
    if is_video:
        _ig_wait(cid)
    return _post(f"{ig}/media_publish", {"creation_id": cid})["id"]


def publish_facebook(kind: str, media_url: str, caption: str = "") -> str:
    page = env("META_PAGE_ID")
    is_video = media_url.lower().endswith((".mp4", ".mov"))
    if kind == "story":
        if is_video:
            return "omitido: historias de video en Facebook requieren carga por partes"
        photo = _post(f"{page}/photos", {"url": media_url, "published": "false"})["id"]
        return _post(f"{page}/photo_stories", {"photo_id": photo}).get("post_id", photo)
    if is_video:
        return _post(f"{page}/videos", {"file_url": media_url, "description": caption})["id"]
    return _post(f"{page}/photos", {"url": media_url, "caption": caption})["id"]


# ---------------- Mensajes directos ----------------

def _send_dm_json(recipient: dict, text: str) -> None:
    r = httpx.post(_url(f"{env('META_PAGE_ID')}/messages"), params=_tok(), timeout=30,
                   json={"recipient": recipient, "messaging_type": "RESPONSE", "message": {"text": text[:1000]}})
    if r.status_code >= 400:
        raise RuntimeError(f"DM falló: {r.text[:300]}")


def send_dm(p: Prospect, text: str) -> None:
    _send_dm_json({"id": p.instagram_id or p.facebook_id}, text)


def _prospect_for(s, platform: str, user_id: str, name: str = "") -> Prospect:
    key = {"instagram_id": user_id} if platform == "instagram" else {"facebook_id": user_id}
    p = find_prospect(s, **key)
    if not p:
        p = Prospect(source="Instagram" if platform == "instagram" else "Facebook",
                     contact_name=name[:200], phone_kind="unknown", **key)
        s.add(p)
        s.flush()
    return p


def handle_dm(platform: str, sender_id: str, mid: str, text: str) -> None:
    with session() as s:
        if mid and s.scalar(select(Message.id).where(Message.external_id == mid)):
            return
        p = _prospect_for(s, platform, sender_id)
        s.add(Message(prospect_id=p.id, channel=platform, direction="in", body=text, external_id=mid,
                      status="received"))
        s.flush()
        reply, _ = bot.handle_inbound(s, p, platform, text)
        if reply:
            try:
                _send_dm_json({"id": sender_id}, reply)
                s.add(Message(prospect_id=p.id, channel=platform, direction="out", body=reply,
                              kind="bot", status="sent"))
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo responder DM: %s", e)


# ---------------- Comentarios ----------------

CLASSIFY_SYSTEM = """Clasificas comentarios en las redes de Pagoya (software de cobranza para academias en México).
Devuelve JSON: {"tipo": "spam"|"negativo"|"prospecto"|"otro", "respuesta_publica": "..."}
- spam: promociones ajenas, links sospechosos, bots, "check my profile", ofertas de seguidores.
- negativo: quejas, críticas, enojo, problemas con el servicio o con un cobro.
- prospecto: preguntan precio, cómo funciona, si sirve para su negocio, piden información.
- otro: felicitaciones, emojis, etiquetas a amigos.
respuesta_publica: para "prospecto" una frase corta y cálida invitando a revisar su DM (sin precios);
para "otro" un agradecimiento breve o "" si no amerita; para spam y negativo siempre ""."""


def classify_comment(text: str) -> dict:
    try:
        return llm.ask_json(CLASSIFY_SYSTEM, f"Comentario: «{text[:1500]}»", max_tokens=2000, effort="low")
    except Exception:  # noqa: BLE001
        log.exception("No se pudo clasificar comentario")
        return {"tipo": "negativo", "respuesta_publica": ""}  # ante la duda, que lo vea Marcelo


def handle_comment(platform: str, comment_id: str, author_id: str, author_name: str, text: str) -> str:
    c = classify_comment(text)
    tipo = c.get("tipo", "otro")
    if tipo == "spam":
        if platform == "instagram":
            _post(comment_id, {"hide": "true"})
        else:
            _post(comment_id, {"is_hidden": "true"})
        return "spam"
    if tipo == "negativo":
        notify.owner_alert(f"Comentario negativo en {platform} (no lo contesté)",
                           f"{author_name}: «{text}» — id {comment_id}")
        return "negativo"
    pub = (c.get("respuesta_publica") or "").strip()
    if pub:
        _post(f"{comment_id}/replies" if platform == "instagram" else f"{comment_id}/comments", {"message": pub})
    if tipo == "prospecto" and author_id:
        with session() as s:
            p = _prospect_for(s, platform, author_id, author_name)
            s.add(Message(prospect_id=p.id, channel=platform, direction="in", external_id=comment_id,
                          body=f"[comentario público] {text}", status="received"))
            s.flush()
            reply, _ = bot.handle_inbound(s, p, platform, text)
            if reply:
                try:
                    _send_dm_json({"comment_id": comment_id}, reply)  # respuesta privada
                    s.add(Message(prospect_id=p.id, channel=platform, direction="out", body=reply,
                                  kind="bot", status="sent"))
                except Exception as e:  # noqa: BLE001
                    log.warning("Respuesta privada falló: %s", e)
    return tipo


def process_webhook(payload: dict) -> None:
    obj = payload.get("object")
    platform = "instagram" if obj == "instagram" else "facebook"
    own_ids = {env("META_PAGE_ID"), env("META_IG_USER_ID")}
    for entry in payload.get("entry", []):
        for ev in entry.get("messaging", []):
            msg = ev.get("message") or {}
            sender = ev.get("sender", {}).get("id")
            if not msg or msg.get("is_echo") or sender in own_ids:
                continue
            text = msg.get("text") or ("[adjunto]" if msg.get("attachments") else "")
            if text:
                try:
                    handle_dm(platform, sender, msg.get("mid", ""), text)
                except Exception:  # noqa: BLE001
                    log.exception("Error en DM")
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            try:
                if platform == "instagram" and ch.get("field") == "comments":
                    frm = v.get("from", {})
                    if frm.get("id") in own_ids:
                        continue
                    handle_comment("instagram", v["id"], frm.get("id", ""), frm.get("username", ""),
                                   v.get("text", ""))
                elif platform == "facebook" and ch.get("field") == "feed" and v.get("item") == "comment" \
                        and v.get("verb") == "add":
                    frm = v.get("from", {})
                    if frm.get("id") in own_ids:
                        continue
                    handle_comment("facebook", v["comment_id"], frm.get("id", ""), frm.get("name", ""),
                                   v.get("message", ""))
            except Exception:  # noqa: BLE001
                log.exception("Error en comentario")


# ---------------- Métricas ----------------

def snapshot_metrics() -> dict:
    out = {}
    if not configured():
        return out
    try:
        ig = env("META_IG_USER_ID")
        if ig:
            out["ig_followers"] = _get(ig, {"fields": "followers_count"}).get("followers_count", 0)
            ins = _get(f"{ig}/insights", {"metric": "reach", "period": "day"}).get("data", [])
            if ins and ins[0].get("values"):
                out["ig_reach"] = ins[0]["values"][-1].get("value", 0)
        page = _get(env("META_PAGE_ID"), {"fields": "followers_count,fan_count"})
        out["fb_followers"] = page.get("followers_count") or page.get("fan_count") or 0
        try:
            pins = _get(f"{env('META_PAGE_ID')}/insights",
                        {"metric": "page_impressions_unique", "period": "day"}).get("data", [])
            if pins and pins[0].get("values"):
                out["fb_reach"] = pins[0]["values"][-1].get("value", 0)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        log.warning("Métricas de Meta fallaron: %s", e)
    return out


def ad_spend_today() -> float | None:
    acct = env("META_AD_ACCOUNT_ID")
    if not (acct and configured()):
        return None
    try:
        data = _get(f"act_{acct}/insights", {"fields": "spend", "date_preset": "today"}).get("data", [])
        return float(data[0]["spend"]) if data else 0.0
    except Exception as e:  # noqa: BLE001
        log.warning("Gasto de anuncios falló: %s", e)
        return None
