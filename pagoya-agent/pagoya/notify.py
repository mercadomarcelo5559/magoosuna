"""Avisos inmediatos para Marcelo (por correo)."""
from __future__ import annotations

import html
import logging

from .approvals import link
from .mailer import send_owner
from .timeutil import fmt_es

log = logging.getLogger(__name__)


def _safe_send(subject: str, body_html: str) -> None:
    try:
        send_owner(subject, body_html)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo mandar aviso: %s", subject)


def owner_alert(subject: str, text: str) -> None:
    _safe_send(f"[Pagoya] {subject}", f"<p>{html.escape(text)}</p>")


def _chat_link(p) -> str:
    return link(f"/admin/chat/{p.id}", p.id)


def demo_booked(demo, p) -> None:
    _safe_send(
        f"[Pagoya] Demo agendada: {demo.academy or p.name} — {fmt_es(demo.start_local)}",
        f"""<h2>Nueva demo</h2><ul>
<li><b>Fecha:</b> {fmt_es(demo.start_local)} (Monterrey)</li>
<li><b>Contacto:</b> {html.escape(demo.contact_name or '')}</li>
<li><b>Academia:</b> {html.escape(demo.academy or '')} ({html.escape(p.category or '')}, {html.escape(p.city or '')})</li>
<li><b>Alumnos:</b> {demo.students or '¿?'}</li>
<li><b>Teléfono:</b> {html.escape(demo.phone or '')}</li>
<li><b>Origen:</b> {html.escape(p.source or '')}</li>
<li><b>Zoom:</b> <a href="{demo.zoom_url}">{demo.zoom_url}</a></li></ul>
<p><a href="{_chat_link(p)}">Ver conversación</a></p>""")


def handoff(p, reason: str, channel: str) -> None:
    _safe_send(
        f"[Pagoya] Te necesitan: {p.name or p.contact_name or p.phone} ({channel})",
        f"""<p><b>Motivo:</b> {html.escape(reason)}</p>
<p>{html.escape(p.name or '')} · {html.escape(p.phone or p.email or '')} · {channel}</p>
<p>El bot quedó en pausa para esta conversación. <a href="{_chat_link(p)}">Abrir conversación y responder</a></p>""")


def paused_message(p, text: str, channel: str) -> None:
    _safe_send(
        f"[Pagoya] Nuevo mensaje de {p.name or p.phone} (conversación contigo)",
        f"""<p>«{html.escape(text[:1000])}»</p><p><a href="{_chat_link(p)}">Responder</a></p>""")
