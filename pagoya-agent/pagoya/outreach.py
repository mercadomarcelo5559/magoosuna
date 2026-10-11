"""Invitaciones, seguimiento, calidad del número y procesamiento de WhatsApp."""
from __future__ import annotations

import datetime as dt
import logging
import re

from sqlalchemy import and_, func, select

from . import bot, notify, whatsapp
from .approvals import link
from .config import env, public_url, settings
from .db import (CLIENTE, INVITADO, NUEVO, Demo, Message, Prospect, find_prospect,
                 kv_get, kv_set, session, utcnow)
from .phones import normalize_mx
from .timeutil import fmt_es, hm, local_naive, to_utc_naive

log = logging.getLogger(__name__)

GIRO_PHRASE = {
    "natación": "academias de natación", "idiomas": "escuelas de idiomas", "música": "academias de música",
    "artes marciales": "academias de artes marciales", "gimnasia": "escuelas de gimnasia",
    "guardería": "guarderías", "gimnasio": "gimnasios", "crossfit": "boxes de crossfit",
    "box": "gimnasios de box", "pilates": "estudios de pilates", "yoga": "estudios de yoga",
    "baile": "academias de baile", "pádel y tenis": "clubes de pádel y tenis",
}
REF_RE = re.compile(r"\b(PY[A-Z0-9]{5})\b", re.I)
DELIVERED = ("delivered", "read")


def giro_phrase(category: str) -> str:
    return GIRO_PHRASE.get((category or "").lower(), "academias y negocios con mensualidades")


# ---------------- Calidad del número ----------------

def quality_factor(s) -> float:
    if kv_get(s, "wa_paused", {}).get("paused"):
        return 0.0
    q = kv_get(s, "wa_quality", {}).get("quality_rating", "UNKNOWN")
    return settings()["whatsapp"]["quality_factor"].get(q, 1.0)


def apply_quality(s, rating: str, source: str = "api") -> None:
    rating = (rating or "UNKNOWN").upper()
    prev = kv_get(s, "wa_quality", {}).get("quality_rating", "UNKNOWN")
    kv_set(s, "wa_quality", {"quality_rating": rating, "checked_at": utcnow().isoformat(), "source": source})
    if rating == prev:
        return
    if rating == "RED":
        kv_set(s, "wa_paused", {"paused": True, "reason": "quality RED", "at": utcnow().isoformat()})
        notify.owner_alert(
            "URGENTE: calidad del número en ROJO — envíos pausados",
            "Pausé todas las invitaciones y seguimientos. El bot sigue contestando a quien escriba. "
            f"Cuando quieras reanudar abre: {link('/admin/resume', 'resume')}")
    elif rating == "YELLOW":
        notify.owner_alert(
            "Calidad del número en AMARILLO — volumen reducido a la mitad",
            "Reduje las invitaciones al 50%. Revisa qué plantilla está generando bloqueos o reportes.")
    elif rating == "GREEN" and prev in ("YELLOW", "RED"):
        notify.owner_alert("Calidad del número de vuelta en VERDE",
                           "El volumen normal se restablece (si estaba pausado por rojo, sigue pausado "
                           "hasta que lo reanudes).")


def check_quality() -> str:
    try:
        data = whatsapp.quality_rating()
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo consultar calidad: %s", e)
        return "UNKNOWN"
    with session() as s:
        apply_quality(s, data["quality_rating"])
        kv_set(s, "wa_number_info", data)
    return data["quality_rating"]


# ---------------- Invitaciones ----------------

def current_slot(now: dt.datetime | None = None) -> tuple[str, dt.datetime, dt.datetime] | None:
    now = now or local_naive()
    if now.weekday() > 4:
        return None
    for name, w in settings()["whatsapp"]["slots"].items():
        start = dt.datetime.combine(now.date(), hm(w["start"]))
        end = dt.datetime.combine(now.date(), hm(w["end"]))
        if start <= now < end:
            return name, start, end
    return None


def slot_counts(s, start_local: dt.datetime, end_local: dt.datetime, kind: str = "invitation") -> dict:
    a, b = to_utc_naive(start_local), to_utc_naive(end_local)
    base = and_(Message.kind == kind, Message.created_at >= a, Message.created_at < b)
    delivered = s.scalar(select(func.count()).where(base, Message.status.in_(DELIVERED))) or 0
    grace = utcnow() - dt.timedelta(minutes=settings()["whatsapp"]["pending_grace_minutes"])
    pending = s.scalar(select(func.count()).where(
        base, Message.status.in_(("", "sent", "accepted")), Message.created_at >= grace)) or 0
    attempted = s.scalar(select(func.count()).where(base)) or 0
    return {"delivered": delivered, "pending": pending, "attempted": attempted}


def eligible_prospects(s, limit: int):
    q = (select(Prospect)
         .where(Prospect.status == NUEVO, Prospect.do_not_contact.is_(False),
                Prospect.phone.is_not(None), Prospect.invited_at.is_(None),
                Prospect.phone_kind.not_in(("fixed", "no_whatsapp")), Prospect.hot.is_(False))
         .order_by(Prospect.reviews.desc().nulls_last(), Prospect.id)
         .limit(limit))
    return list(s.scalars(q))


def invitation_params(p: Prospect) -> list[str]:
    return [p.name or "tu academia", giro_phrase(p.category)]


def send_logged(s, p: Prospect, template: str, params: list[str], kind: str, body_preview: str,
                button_param: str | None = None) -> bool:
    try:
        mid = whatsapp.send_template(p.phone, template, params, button_param)
        s.add(Message(prospect_id=p.id, channel="whatsapp", direction="out", kind=kind,
                      template=template, body=body_preview, external_id=mid, status="sent"))
        return True
    except whatsapp.WhatsAppError as e:
        s.add(Message(prospect_id=p.id, channel="whatsapp", direction="out", kind=kind,
                      template=template, body=body_preview, status="failed", error=str(e)))
        if e.code in whatsapp.UNDELIVERABLE_CODES:
            p.phone_kind = "no_whatsapp"
        log.warning("Envío falló a %s: %s", p.phone, e)
        return False


def invitation_text(p: Prospect) -> str:
    n, g = invitation_params(p)
    return (f"Hola, ¿qué tal equipo de {n}? Soy Marcelo de Pagoya. Ayudamos a {g} a cobrar sus "
            "mensualidades sin perseguir a nadie: recordatorios automáticos por WhatsApp y pagos con "
            "tarjeta u OXXO. ¿Te muestro en 15 minutos cómo funciona? Responde BAJA si no te interesa.")


def run_invitations(now: dt.datetime | None = None) -> dict:
    """Se ejecuta cada 10 min. Completa la cuota del turno contando solo ENTREGADOS."""
    slot = current_slot(now)
    if not slot:
        return {"skipped": "fuera de horario"}
    name, start, end = slot
    cfg = settings()["whatsapp"]
    with session() as s:
        factor = quality_factor(s)
        quota = int(cfg["invitations_per_slot"] * factor)
        c = slot_counts(s, start, end)
        remaining = quota - c["delivered"] - c["pending"]
        # tope duro de intentos para no quemar la lista si muchos fallan
        hard_cap = int(quota * 1.6) - c["attempted"]
        n = max(0, min(remaining, cfg["send_chunk"], hard_cap))
        sent = 0
        for p in eligible_prospects(s, n):
            p.invited_at = utcnow()
            if send_logged(s, p, cfg["templates"]["invitation"], invitation_params(p), "invitation",
                           invitation_text(p)):
                sent += 1
            s.flush()
        return {"slot": name, "quota": quota, **c, "sent_now": sent}


def run_followups() -> dict:
    """Un solo seguimiento a los N días a quien no respondió."""
    cfg = settings()["whatsapp"]
    if not current_slot():
        return {"skipped": "fuera de horario"}
    with session() as s:
        factor = quality_factor(s)
        if factor == 0:
            return {"skipped": "pausado"}
        cutoff = to_utc_naive(local_naive().replace(hour=23, minute=59)
                              - dt.timedelta(days=cfg["followup_after_days"]))
        today0 = to_utc_naive(dt.datetime.combine(local_naive().date(), dt.time()))
        done_today = s.scalar(select(func.count()).where(Message.kind == "followup",
                                                         Message.created_at >= today0)) or 0
        limit = max(0, int(cfg["invitations_per_slot"] * factor) - done_today)
        limit = min(limit, cfg["send_chunk"])
        q = (select(Prospect).where(
            Prospect.status == INVITADO, Prospect.do_not_contact.is_(False),
            Prospect.followup_sent_at.is_(None), Prospect.last_inbound_at.is_(None),
            Prospect.invited_at <= cutoff, Prospect.phone.is_not(None))
            .order_by(Prospect.invited_at).limit(limit))
        sent = 0
        for p in s.scalars(q):
            p.followup_sent_at = utcnow()
            n, g = invitation_params(p)
            text = (f"Hola de nuevo, equipo de {n}. Te escribí hace unos días sobre Pagoya: "
                    "nosotros cargamos tu lista de alumnos gratis y en 1 día ya mandas recordatorios "
                    "y cobras con tarjeta u OXXO. ¿Te agendo una demo de 15 minutos? Responde BAJA si "
                    "prefieres no recibir mensajes.")
            if send_logged(s, p, cfg["templates"]["followup"], [n], "followup", text):
                sent += 1
        return {"followups": sent}


# ---------------- Webhook: estatus y mensajes ----------------

def apply_status(s, st: dict) -> None:
    m = s.scalar(select(Message).where(Message.external_id == st["id"]))
    if not m:
        return
    order = {"": 0, "accepted": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}
    new = st["status"]
    if order.get(new, 0) >= order.get(m.status, 0) or new == "failed":
        m.status = new
    if new in DELIVERED and not m.delivered_at:
        m.delivered_at = utcnow()
        if m.prospect and m.kind == "invitation":
            m.prospect.advance(INVITADO)
    if new == "failed":
        m.error = f"{st.get('error_code')}: {st.get('error')}"
        if m.prospect and st.get("error_code") in whatsapp.UNDELIVERABLE_CODES:
            m.prospect.phone_kind = "no_whatsapp"


def get_or_create_from_wa(s, wa_from: str, profile_name: str, text: str, referral: dict | None) -> Prospect:
    phone = normalize_mx(wa_from) or ("+" + wa_from)
    p = find_prospect(s, phone=phone)
    if p:
        return p
    source = "WhatsApp directo"
    if referral:
        source = "Anuncios"
    referrer = None
    m = REF_RE.search(text or "")
    if m:
        referrer = s.scalar(select(Prospect).where(Prospect.referral_code == m.group(1).upper()))
        if referrer:
            source = "Referido"
    low = (text or "").lower()
    if "calculadora" in low:
        source = "Calculadora"
    elif any(k in low for k in ("capterra", "getapp", "software advice", "directorio", "comparasoftware")):
        source = "Directorio"
    elif "google" in low and ("perfil" in low or "maps" in low or "reseña" in low):
        source = "Google Business"
    elif "vi su página" in (text or "").lower() or "pagoya.com.mx" in (text or "").lower():
        source = "SEO"
    p = Prospect(phone=phone, contact_name=profile_name[:200], source=source, status=NUEVO,
                 phone_kind="mobile", referred_by_id=referrer.id if referrer else None)
    s.add(p)
    s.flush()
    return p


def process_inbound(msg: dict) -> None:
    with session() as s:
        if s.scalar(select(Message.id).where(Message.external_id == msg["id"])):
            return  # duplicado de Meta
        p = get_or_create_from_wa(s, msg["from"], msg.get("profile_name", ""), msg["text"], msg.get("referral"))
        s.add(Message(prospect_id=p.id, channel="whatsapp", direction="in", body=msg["text"],
                      external_id=msg["id"], status="received"))
        s.flush()
        whatsapp.mark_read(msg["id"])
        text, out = bot.handle_inbound(s, p, "whatsapp", msg["text"])
        if text:
            try:
                mid = whatsapp.send_text(p.phone, text)
                s.add(Message(prospect_id=p.id, channel="whatsapp", direction="out", body=text,
                              external_id=mid, status="sent", kind="bot"))
            except whatsapp.WhatsAppError as e:
                log.error("No se pudo responder a %s: %s", p.phone, e)
                s.add(Message(prospect_id=p.id, channel="whatsapp", direction="out", body=text,
                              status="failed", error=str(e), kind="bot"))


def process_webhook(payload: dict) -> None:
    messages, statuses, alerts = whatsapp.parse_webhook(payload)
    if statuses:
        with session() as s:
            for st in statuses:
                apply_status(s, st)
    if alerts:
        check_quality()  # ante cualquier alerta de calidad consultamos el rating real
    for m in messages:
        try:
            process_inbound(m)
        except Exception:  # noqa: BLE001
            log.exception("Error procesando mensaje %s", m.get("id"))


# ---------------- Prospectos calientes, referidos, reseñas, recordatorios ----------------

def contact_hot_leads() -> int:
    """Prospectos de la calculadora: escribirles en menos de 5 minutos."""
    tpl = settings()["whatsapp"]["templates"]["calculator"]
    n = 0
    with session() as s:
        q = select(Prospect).where(Prospect.hot.is_(True), Prospect.invited_at.is_(None),
                                   Prospect.do_not_contact.is_(False), Prospect.phone.is_not(None))
        for p in s.scalars(q):
            p.invited_at = utcnow()
            loss = (p.notes.split("pérdida_anual=")[-1].split()[0] if "pérdida_anual=" in (p.notes or "") else "")
            name = p.contact_name or "hola"
            text = (f"Hola {name}, soy Marcelo de Pagoya. Vi tu resultado en la calculadora: "
                    f"{p.name or 'tu academia'} podría estar perdiendo ${loss} al año por pagos atrasados. "
                    "¿Te muestro en 15 minutos cómo recuperarlo con recordatorios automáticos y pagos en OXXO?")
            if send_logged(s, p, tpl, [name, p.name or "tu academia", loss or "dinero"], "calculator", text):
                p.advance(INVITADO)
                n += 1
    return n


def referral_link(code: str) -> str:
    return public_url(f"/r/{code}")


def ensure_referral_code(s, p: Prospect) -> str:
    import secrets
    if not p.referral_code:
        while True:
            code = "PY" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))
            if not s.scalar(select(Prospect.id).where(Prospect.referral_code == code)):
                break
        p.referral_code = code
    return p.referral_code


def run_client_nudges() -> dict:
    """30 días: invitar a referir. 15 días: pedir reseña en Google."""
    cfg = settings()
    tpl = cfg["whatsapp"]["templates"]
    now = utcnow()
    res = {"referral_invites": 0, "review_requests": 0}
    with session() as s:
        base = and_(Prospect.status == CLIENTE, Prospect.do_not_contact.is_(False),
                    Prospect.phone.is_not(None), Prospect.client_since.is_not(None))
        for p in s.scalars(select(Prospect).where(
                base, Prospect.referral_invite_sent_at.is_(None),
                Prospect.client_since <= now - dt.timedelta(days=cfg["referrals"]["invite_after_days"]))):
            code = ensure_referral_code(s, p)
            p.referral_invite_sent_at = now
            text = (f"¡Hola {p.contact_name or ''}! Ya cumplieron un mes con Pagoya. Si recomiendas a otra "
                    f"academia y se vuelve cliente, tú ganas 1 mes gratis y ellos 50% en su primer mes. "
                    f"Tu link: {referral_link(code)}")
            if send_logged(s, p, tpl["referral_invite"], [p.contact_name or p.name or "", code], "referral",
                           text, button_param=code):
                res["referral_invites"] += 1
        review_link = env("GOOGLE_REVIEW_LINK")
        if review_link:
            for p in s.scalars(select(Prospect).where(
                    base, Prospect.review_request_sent_at.is_(None),
                    Prospect.client_since <= now - dt.timedelta(days=cfg["reviews"]["ask_after_days"]))):
                p.review_request_sent_at = now
                text = (f"Hola {p.contact_name or ''}, ¿cómo te ha ido con Pagoya? Si te está ayudando, "
                        f"nos ayudaría muchísimo una reseña en Google: {review_link}")
                if send_logged(s, p, tpl["review_request"], [p.contact_name or p.name or ""], "review", text):
                    res["review_requests"] += 1
    return res


def run_demo_reminders() -> int:
    tpl = settings()["whatsapp"]["templates"]["demo_reminder"]
    now = local_naive()
    n = 0
    with session() as s:
        q = select(Demo).where(Demo.cancelled.is_(False), Demo.reminder_sent.is_(False),
                               Demo.start_local > now, Demo.start_local <= now + dt.timedelta(hours=2))
        for d in s.scalars(q):
            d.reminder_sent = True
            p = d.prospect
            if not p or not p.phone or p.do_not_contact:
                continue
            text = f"Hola {d.contact_name}, te recuerdo tu demo de Pagoya {fmt_es(d.start_local)}: {d.zoom_url}"
            if send_logged(s, p, tpl, [d.contact_name or "", d.start_local.strftime("%H:%M"), d.zoom_url],
                           "reminder", text):
                n += 1
    return n


def mark_client(s, p: Prospect) -> None:
    if p.status != CLIENTE:
        p.status = CLIENTE
        p.client_since = utcnow()
        ensure_referral_code(s, p)


def manual_send(prospect_id: int, text: str) -> str:
    """Tú respondes desde el panel (dentro de la ventana de 24 h)."""
    with session() as s:
        p = s.get(Prospect, prospect_id)
        if p.instagram_id or p.facebook_id:
            from . import social
            if p.phone is None:
                social.send_dm(p, text)
                s.add(Message(prospect_id=p.id, channel="instagram" if p.instagram_id else "facebook",
                              direction="out", body=text, kind="manual", status="sent"))
                return "ok"
        mid = whatsapp.send_text(p.phone, text)
        s.add(Message(prospect_id=p.id, channel="whatsapp", direction="out", body=text,
                      external_id=mid, status="sent", kind="manual"))
        return mid
