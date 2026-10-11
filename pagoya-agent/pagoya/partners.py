"""Alianzas: lista de aliados, propuesta de comisión 20% y contacto SOLO tras tu aprobación."""
from __future__ import annotations

import html
import logging

from sqlalchemy import select

from . import llm, mailer
from .approvals import link
from .coldemail import _footer_text, _html, unsubscribe_url
from .db import Approval, Partner, session, utcnow
from .mailer import send_cold
from .places import run_partner_search

log = logging.getLogger(__name__)

PROPOSAL_SYSTEM = """Redactas propuestas de alianza comercial para Pagoya (software de cobranza automática para academias y negocios con mensualidades en México: recordatorios por WhatsApp, pagos con tarjeta y OXXO, panel del dueño, configuración gratis).
Español de México, profesional y concreto."""


def draft_proposal() -> int:
    prompt = """Redacta:
1) "propuesta": documento corto (máx 350 palabras) del programa de aliados: comisión del 20% de lo que pague el cliente durante su primer año por cada cliente que nos traigan; cómo se registra el referido (link o código único), cuándo se paga (mensual, al cobrar el cliente), sin exclusividad ni costo para el aliado, y beneficio para sus clientes (configuración gratis).
2) "correo": correo inicial breve para contadores, ligas/federaciones deportivas, escuelas de entrenadores y proveedores de uniformes/equipo, con {nombre} y {tipo} como variables.
JSON: {"propuesta": "...", "asunto": "...", "correo": "..."}"""
    data = llm.ask_json(PROPOSAL_SYSTEM, prompt, max_tokens=8000)
    with session() as s:
        counts = {}
        for p in s.scalars(select(Partner).where(Partner.status == "lista")):
            counts[p.kind] = counts.get(p.kind, 0) + 1
        ap = Approval(kind="partners", ref="programa-aliados", payload=data)
        s.add(ap)
        s.flush()
        aid = ap.id
    mailer.send_owner(
        "[Pagoya] Propuesta de alianzas (20% primer año) — necesita tu OK",
        f"""<h2>Programa de aliados</h2><pre style="white-space:pre-wrap;font-family:Arial">{html.escape(data['propuesta'])}</pre>
<h3>Correo que mandaríamos</h3><p><b>{html.escape(data['asunto'])}</b></p>
<pre style="white-space:pre-wrap;font-family:Arial">{html.escape(data['correo'])}</pre>
<p>Aliados en lista: {counts or 'ninguno aún (corre la búsqueda de aliados)'}</p>
<p>No contacto a nadie hasta que apruebes: <a href="{link(f'/approve/partners/{aid}', 'partners', aid)}">✅ Aprobar</a> |
<a href="{link(f'/changes/partners/{aid}', 'partners', aid)}">✏️ Pedir cambios</a></p>""")
    return aid


def contact_partners(limit: int = 10) -> int:
    """Corre a diario; solo actúa si hay una propuesta aprobada."""
    with session() as s:
        ap = s.scalar(select(Approval).where(Approval.kind == "partners", Approval.status == "approved")
                      .order_by(Approval.id.desc()))
        if not ap:
            return 0
        n = 0
        for pa in s.scalars(select(Partner).where(Partner.status == "lista", Partner.email != "").limit(limit)):
            body = ap.payload["correo"].replace("{nombre}", pa.name).replace("{tipo}", pa.kind)
            send_cold(pa.email, ap.payload["asunto"], body + _footer_text(pa.email), _html(body, pa.email),
                      unsubscribe_url(pa.email))
            pa.status, pa.contacted_at = "contactado", utcnow()
            n += 1
        return n


def build_list() -> int:
    return run_partner_search()
