"""Cliente de WhatsApp Cloud API (oficial). Solo plantillas aprobadas para iniciar conversación."""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from .config import env, graph_version, settings, test_mode
from .phones import normalize_mx, wa_number

log = logging.getLogger(__name__)

# Errores que significan "este número no tiene WhatsApp / no se puede entregar"
UNDELIVERABLE_CODES = {131026, 131021, 131030}
# Error de Meta por política de marketing (el usuario no recibe marketing de negocios): no reintentar
MARKETING_BLOCKED_CODES = {131049, 131050}


class WhatsAppError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{graph_version()}/{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {env('WHATSAPP_TOKEN')}"}


def configured() -> bool:
    return bool(env("WHATSAPP_TOKEN") and env("WHATSAPP_PHONE_NUMBER_ID"))


def resolve_recipient(e164: str) -> str:
    """En modo prueba todo se manda a tu número personal."""
    if test_mode():
        owner = normalize_mx(env("OWNER_WHATSAPP"))
        if not owner:
            raise WhatsAppError("TEST_MODE activo pero OWNER_WHATSAPP no es válido")
        return wa_number(owner)
    return wa_number(e164)


def _post(payload: dict) -> str:
    if not configured():
        raise WhatsAppError("WhatsApp no configurado (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID)")
    r = httpx.post(_url(f"{env('WHATSAPP_PHONE_NUMBER_ID')}/messages"),
                   headers=_headers(), json=payload, timeout=30)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        err = data.get("error", {})
        raise WhatsAppError(err.get("message", r.text), err.get("code"))
    return data["messages"][0]["id"]


def send_template(to_e164: str, template: str, body_params: list[str] | None = None,
                  button_url_param: str | None = None) -> str:
    components = []
    if body_params:
        components.append({"type": "body",
                           "parameters": [{"type": "text", "text": str(p)[:1000]} for p in body_params]})
    if button_url_param:
        components.append({"type": "button", "sub_type": "url", "index": "0",
                           "parameters": [{"type": "text", "text": button_url_param}]})
    payload = {
        "messaging_product": "whatsapp",
        "to": resolve_recipient(to_e164),
        "type": "template",
        "template": {"name": template,
                     "language": {"code": settings()["whatsapp"]["template_language"]},
                     "components": components},
    }
    return _post(payload)


def send_text(to_e164: str, text: str) -> str:
    """Texto libre: solo válido dentro de la ventana de 24 h después de que el prospecto escribió."""
    return _post({"messaging_product": "whatsapp", "to": resolve_recipient(to_e164),
                  "type": "text", "text": {"body": text[:4096], "preview_url": True}})


def mark_read(message_id: str) -> None:
    try:
        _post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
    except Exception:  # no es crítico
        pass


def quality_rating() -> dict:
    """{'quality_rating': 'GREEN'|'YELLOW'|'RED'|'UNKNOWN', 'messaging_limit_tier': ...}"""
    if not configured():
        return {"quality_rating": "UNKNOWN"}
    r = httpx.get(_url(env("WHATSAPP_PHONE_NUMBER_ID")), headers=_headers(), timeout=30,
                  params={"fields": "quality_rating,messaging_limit_tier,display_phone_number,"
                                    "verified_name,throughput,name_status"})
    r.raise_for_status()
    data = r.json()
    data["quality_rating"] = (data.get("quality_rating") or "UNKNOWN").upper()
    return data


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    secret = env("META_APP_SECRET")
    if not secret:
        return True  # sin secreto configurado no validamos (solo para pruebas)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


def parse_webhook(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Devuelve (mensajes entrantes, estatus de entregas, alertas de calidad)."""
    messages, statuses, alerts = [], [], []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {})
            if field == "messages":
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                            for c in value.get("contacts", [])}
                for m in value.get("messages", []):
                    text = ""
                    t = m.get("type")
                    if t == "text":
                        text = m["text"]["body"]
                    elif t == "button":
                        text = m["button"].get("text", "")
                    elif t == "interactive":
                        it = m["interactive"]
                        text = (it.get("button_reply") or it.get("list_reply") or {}).get("title", "")
                    elif t in ("image", "document"):
                        text = f"[{t} recibido] " + (m[t].get("caption") or m[t].get("filename") or "")
                    elif t == "contacts":
                        parts = []
                        for c in m.get("contacts", []):
                            nm = c.get("name", {}).get("formatted_name", "")
                            ph = ", ".join(p.get("phone", "") for p in c.get("phones", []))
                            org = c.get("org", {}).get("company", "")
                            parts.append(f"{nm} ({org}) {ph}".strip())
                        text = "[contacto compartido] " + "; ".join(parts)
                    elif t == "audio":
                        text = "[nota de voz]"
                    else:
                        text = f"[{t}]"
                    messages.append({
                        "id": m.get("id"), "from": m.get("from"), "type": t, "text": text,
                        "profile_name": contacts.get(m.get("from"), ""),
                        "referral": m.get("referral"),  # clic en anuncio Click-to-WhatsApp
                        "raw": m,
                    })
                for st in value.get("statuses", []):
                    errs = st.get("errors") or []
                    statuses.append({"id": st.get("id"), "status": st.get("status"),
                                     "recipient": st.get("recipient_id"),
                                     "error_code": errs[0].get("code") if errs else None,
                                     "error": errs[0].get("title", "") if errs else ""})
            elif field in ("phone_number_quality_update", "account_alerts", "account_update"):
                alerts.append({"field": field, "value": value})
    return messages, statuses, alerts
