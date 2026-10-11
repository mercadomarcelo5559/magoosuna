"""Correo en frío a correos PÚBLICOS de negocios. Máx 50/día, baja inmediata, 1 seguimiento."""
from __future__ import annotations

import datetime as dt
import html
import logging
import re

from sqlalchemy import func, select

from . import notify
from .approvals import link
from .config import env, settings
from .db import BAJA, INVITADO, NUEVO, RESPONDIO, Message, Partner, Prospect, session, utcnow
from .mailer import fetch_unseen, send_cold, strip_quoted
from .outreach import giro_phrase
from .phones import normalize_mx
from .timeutil import hm, local_naive, to_utc_naive

log = logging.getLogger(__name__)
OPT_OUT = re.compile(r"\b(baja|unsubscribe|no me interesa|no gracias|remover|eliminar)\b", re.I)
PHONE_RE = re.compile(r"(\+?52)?[\s\-\.]?\(?\d{2,3}\)?[\s\-\.]?\d{3,4}[\s\-\.]?\d{4}")


def unsubscribe_url(email: str) -> str:
    return link(f"/baja/email/{email}", "unsub", email)


def _footer_text(email: str) -> str:
    return (f"\n\n--\n{env('COLD_EMAIL_FROM_NAME', 'Pagoya')} · www.pagoya.com.mx · {env('BUSINESS_ADDRESS')}\n"
            f"Te escribo porque tu correo aparece publicado en el sitio de tu negocio. "
            f"Si no quieres recibir más correos responde BAJA o entra aquí: {unsubscribe_url(email)}")


def _html(text: str, email: str) -> str:
    body = html.escape(text).replace("\n", "<br>")
    return (f"<div style='font-family:Arial;font-size:15px'>{body}</div>"
            f"<p style='font-size:12px;color:#777'>{env('COLD_EMAIL_FROM_NAME', 'Pagoya')} · "
            f"www.pagoya.com.mx · {html.escape(env('BUSINESS_ADDRESS'))}<br>Te escribo porque tu correo aparece "
            f"publicado en el sitio de tu negocio. <a href='{unsubscribe_url(email)}'>Darme de baja</a></p>")


def initial(p: Prospect) -> tuple[str, str]:
    wa = env("WHATSAPP_PUBLIC_NUMBER")
    subject = f"{p.name}: cobrar mensualidades sin perseguir a nadie"
    text = (f"Hola, equipo de {p.name}:\n\n"
            f"Soy Marcelo, de Pagoya. Trabajamos con {giro_phrase(p.category)} en {p.city or 'Monterrey'} "
            "que se cansaron de perseguir pagos cada mes.\n\n"
            "Pagoya manda recordatorios automáticos por WhatsApp, cobra con tarjeta y OXXO, y te muestra "
            "en un panel quién ya pagó y quién debe. Además cargamos tu lista de alumnos gratis.\n\n"
            "¿Te muestro cómo funciona en una llamada de 15 minutos por Zoom esta semana?\n"
            f"Puedes responder este correo o escribirme por WhatsApp: https://wa.me/{wa}\n\nSaludos,\nMarcelo")
    return subject, text


def followup(p: Prospect) -> tuple[str, str]:
    text = (f"Hola de nuevo, equipo de {p.name}:\n\n"
            "Solo para no dejar esto en el aire: si cobrar mensualidades les quita tiempo, en una demo de "
            "15 minutos te enseño cómo otras academias redujeron sus pagos atrasados con recordatorios "
            "automáticos y pagos en OXXO. ¿Te late el jueves o viernes?\n\nMarcelo")
    return f"Re: {p.name}: cobrar mensualidades sin perseguir a nadie", text


def in_window() -> bool:
    w = settings()["cold_email"]["send_window"]
    now = local_naive()
    return now.weekday() < 5 and hm(w["start"]) <= now.time() < hm(w["end"])


def run_cold_email() -> dict:
    if not in_window():
        return {"skipped": "fuera de horario"}
    cfg = settings()["cold_email"]
    today0 = to_utc_naive(dt.datetime.combine(local_naive().date(), dt.time()))
    with session() as s:
        sent_today = s.scalar(select(func.count()).where(
            Message.channel == "email", Message.direction == "out", Message.created_at >= today0)) or 0
        budget = max(0, cfg["daily_limit"] - sent_today)
        out = {"initial": 0, "followup": 0}
        # 1) seguimientos (prioridad) a los 4 días sin respuesta
        cutoff = utcnow() - dt.timedelta(days=cfg["followup_after_days"])
        fus = s.scalars(select(Prospect).where(
            Prospect.cold_email_sent_at <= cutoff, Prospect.cold_followup_sent_at.is_(None),
            Prospect.do_not_contact.is_(False), Prospect.last_inbound_at.is_(None),
            Prospect.status.in_((NUEVO, INVITADO))).limit(min(budget, 10)))
        for p in fus:
            subj, text = followup(p)
            prev = s.scalar(select(Message.external_id).where(
                Message.prospect_id == p.id, Message.channel == "email", Message.kind == "cold"))
            mid = send_cold(p.email, subj, text + _footer_text(p.email), _html(text, p.email),
                            unsubscribe_url(p.email), in_reply_to=prev)
            p.cold_followup_sent_at = utcnow()
            s.add(Message(prospect_id=p.id, channel="email", direction="out", kind="cold_followup",
                          body=text, external_id=mid, status="sent"))
            out["followup"] += 1
            budget -= 1
        # 2) correos iniciales: prospectos con correo público y que no han respondido por otro canal
        news = s.scalars(select(Prospect).where(
            Prospect.email.is_not(None), Prospect.cold_email_sent_at.is_(None),
            Prospect.do_not_contact.is_(False), Prospect.last_inbound_at.is_(None),
            Prospect.status.in_((NUEVO, INVITADO))).order_by(Prospect.reviews.desc().nulls_last())
            .limit(max(0, budget)))
        for p in news:
            subj, text = initial(p)
            mid = send_cold(p.email, subj, text + _footer_text(p.email), _html(text, p.email),
                            unsubscribe_url(p.email))
            p.cold_email_sent_at = utcnow()
            s.add(Message(prospect_id=p.id, channel="email", direction="out", kind="cold",
                          body=text, external_id=mid, status="sent"))
            out["initial"] += 1
        return out


def unsubscribe(email: str) -> None:
    email = email.lower()
    with session() as s:
        for p in s.scalars(select(Prospect).where(Prospect.email == email)):
            p.advance(BAJA)
        for pa in s.scalars(select(Partner).where(Partner.email == email)):
            pa.status = "no"


def check_replies() -> int:
    """Respuestas al buzón secundario -> CRM (+ aviso a Marcelo)."""
    since = (local_naive() - dt.timedelta(days=10)).strftime("%d-%b-%Y")
    try:
        mails = fetch_unseen(env("COLD_IMAP_HOST", "imap.gmail.com"), env("COLD_EMAIL_USER"),
                             env("COLD_EMAIL_PASSWORD"), since=since)
    except Exception as e:  # noqa: BLE001
        log.warning("IMAP frío falló: %s", e)
        return 0
    n = 0
    for m in mails:
        body = strip_quoted(m["body"])
        with session() as s:
            p = s.scalar(select(Prospect).where(Prospect.email == m["from"]))
            partner = s.scalar(select(Partner).where(Partner.email == m["from"]))
            if not p and not partner:
                continue
            if partner and not p:
                partner.status = "no" if OPT_OUT.search(body) else "interesado"
                notify.owner_alert(f"Respuesta de posible aliado: {partner.name}", body[:2000])
                continue
            s.add(Message(prospect_id=p.id, channel="email", direction="in", body=body[:5000], status="received"))
            p.last_inbound_at = utcnow()
            if OPT_OUT.search(body) and len(body) < 300:
                p.advance(BAJA)
                continue
            p.advance(RESPONDIO)
            ph = PHONE_RE.search(body)
            phone = normalize_mx(ph.group(0)) if ph else None
            if phone and not p.phone and not s.scalar(select(Prospect.id).where(Prospect.phone == phone)):
                p.phone = phone
            n += 1
            notify.owner_alert(f"Respondió por correo: {p.name}",
                               f"{m['from']}: «{body[:1500]}». Contéstale desde contacto@ o pásalo a WhatsApp.")
    return n
