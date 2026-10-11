"""Resumen diario (7:00 pm) y análisis semanal por canal."""
from __future__ import annotations

import datetime as dt
import html

from sqlalchemy import func, select

from . import ads, social
from .db import (CLIENTE, DailyMetric, Demo, Handoff, Message, Prospect, SharedContact, kv_get, session,
                 utcnow)
from .approvals import link
from .mailer import send_owner
from .timeutil import fmt_es, local_day_bounds_utc, local_naive, utc_naive_to_local


def _count(s, *where) -> int:
    return s.scalar(select(func.count()).select_from(Message).where(*where)) or 0


def channel_stats(s, since: dt.datetime) -> list[dict]:
    rows = {}
    for src, n in s.execute(select(Prospect.source, func.count()).where(Prospect.created_at >= since)
                            .group_by(Prospect.source)):
        rows.setdefault(src, {"source": src, "prospects": 0, "demos": 0, "clients": 0})["prospects"] = n
    for src, n in s.execute(select(Demo.source, func.count(func.distinct(Demo.prospect_id)))
                            .where(Demo.created_at >= since, Demo.cancelled.is_(False)).group_by(Demo.source)):
        rows.setdefault(src, {"source": src, "prospects": 0, "demos": 0, "clients": 0})["demos"] = n
    for src, n in s.execute(select(Prospect.source, func.count()).where(
            Prospect.status == CLIENTE, Prospect.client_since >= since).group_by(Prospect.source)):
        rows.setdefault(src, {"source": src, "prospects": 0, "demos": 0, "clients": 0})["clients"] = n
    out = []
    for r in rows.values():
        r["demo_rate"] = r["demos"] / r["prospects"] if r["prospects"] else 0
        r["client_rate"] = r["clients"] / r["prospects"] if r["prospects"] else 0
        out.append(r)
    return sorted(out, key=lambda r: (-r["demos"], -r["prospects"]))


def recommendation(stats: list[dict]) -> str:
    ranked = [r for r in stats if r["prospects"] >= 10]
    if not ranked:
        return "Aún no hay suficientes datos (mínimo 10 prospectos por canal) para recomendar cambios."
    best_demo = max(ranked, key=lambda r: r["demo_rate"])
    best_client = max(ranked, key=lambda r: (r["client_rate"], r["demo_rate"]))
    worst = min(ranked, key=lambda r: r["demo_rate"])
    txt = (f"Mejor canal en demos: {best_demo['source']} ({best_demo['demo_rate']:.0%}). "
           f"Mejor en clientes: {best_client['source']} ({best_client['client_rate']:.0%}). ")
    if worst["source"] != best_demo["source"]:
        txt += (f"Sugerencia: mover esfuerzo/presupuesto de {worst['source']} ({worst['demo_rate']:.0%}) "
                f"hacia {best_demo['source']}.")
    return txt


def build_daily(day: dt.date | None = None) -> tuple[str, str]:
    day = day or local_naive().date()
    a, b = local_day_bounds_utc(day)
    metrics = social.snapshot_metrics()
    spend = ads.ad_spend_today() if ads.active_campaign_exists() else None
    with session() as s:
        today = (Message.created_at >= a, Message.created_at < b)
        inv_sent = _count(s, *today, Message.kind == "invitation")
        inv_deliv = _count(s, *today, Message.kind == "invitation", Message.status.in_(("delivered", "read")))
        fu_sent = _count(s, *today, Message.kind == "followup")
        fu_deliv = _count(s, *today, Message.kind == "followup", Message.status.in_(("delivered", "read")))
        failed = _count(s, *today, Message.direction == "out", Message.status == "failed")
        replies = s.scalar(select(func.count(func.distinct(Message.prospect_id))).where(
            *today, Message.direction == "in")) or 0
        dms = s.scalar(select(func.count()).select_from(Message).where(
            *today, Message.direction == "in", Message.channel.in_(("instagram", "facebook")))) or 0
        social_new = s.scalar(select(func.count()).where(
            Prospect.created_at >= a, Prospect.created_at < b, Prospect.source.in_(("Instagram", "Facebook")))) or 0
        cold = _count(s, *today, Message.channel == "email", Message.direction == "out")
        demos = list(s.scalars(select(Demo).where(Demo.created_at >= a, Demo.created_at < b,
                                                  Demo.cancelled.is_(False)).order_by(Demo.start_local)))
        upcoming = list(s.scalars(select(Demo).where(Demo.start_local >= local_naive(),
                                                     Demo.cancelled.is_(False)).order_by(Demo.start_local).limit(15)))
        shared = list(s.scalars(select(SharedContact).where(SharedContact.created_at >= a,
                                                            SharedContact.created_at < b)))
        shared_rows = []
        for c in shared:
            src = s.get(Prospect, c.from_prospect_id) if c.from_prospect_id else None
            shared_rows.append((c, src))
        handoffs = list(s.scalars(select(Handoff).where(Handoff.created_at >= a, Handoff.created_at < b)))
        quality = kv_get(s, "wa_quality", {}).get("quality_rating", "UNKNOWN")
        paused = kv_get(s, "wa_paused", {}).get("paused", False)
        today_by_source = dict(s.execute(select(Prospect.source, func.count()).where(
            Prospect.created_at >= a, Prospect.created_at < b).group_by(Prospect.source)).all())
        stats30 = channel_stats(s, utcnow() - dt.timedelta(days=30))
        # seguidores nuevos = diferencia contra la foto de ayer
        prev = {m.key: m.value for m in s.scalars(select(DailyMetric).where(
            DailyMetric.day == (day - dt.timedelta(days=1)).isoformat()))}
        for k, v in metrics.items():
            s.add(DailyMetric(day=day.isoformat(), key=k, value=float(v)))
        demo_rows = "".join(
            f"<tr><td>{fmt_es(d.start_local)}</td><td>{html.escape(d.contact_name)}</td>"
            f"<td>{html.escape(d.academy)}</td><td>{d.students or '¿?'}</td><td>{html.escape(d.phone)}</td>"
            f"<td>{html.escape(d.source)}</td></tr>" for d in demos) or "<tr><td colspan=6>Ninguna hoy</td></tr>"
        up_rows = "".join(f"<li>{fmt_es(d.start_local)} — {html.escape(d.academy)} ({html.escape(d.contact_name)}, "
                          f"{html.escape(d.phone)})</li>" for d in upcoming) or "<li>Sin demos próximas</li>"
        shared_html = "".join(
            f"<li>{html.escape(c.name)} — {html.escape(c.academy)} — {html.escape(c.phone)} "
            f"<span style='color:#777'>(lo compartió {html.escape(src.name if src else '')})</span></li>"
            for c, src in shared_rows) or "<li>Ninguno</li>"
        handoff_html = "".join(f"<li>{html.escape((s.get(Prospect, h.prospect_id).name if h.prospect_id else '') or '')}"
                               f" — {html.escape(h.reason)} ({h.channel})</li>" for h in handoffs) or "<li>Ninguna</li>"
    qcolor = {"GREEN": "#1a7f37", "YELLOW": "#b58100", "RED": "#c62828"}.get(quality, "#555")

    def delta(k):
        if k not in metrics:
            return "—"
        return f"{metrics[k] - prev[k]:+.0f}" if k in prev else "(primer registro)"

    src_rows = "".join(
        f"<tr><td>{html.escape(r['source'])}</td><td>{today_by_source.get(r['source'], 0)}</td><td>{r['prospects']}</td>"
        f"<td>{r['demos']} ({r['demo_rate']:.0%})</td><td>{r['clients']} ({r['client_rate']:.0%})</td></tr>"
        for r in stats30) or "<tr><td colspan=5>Sin datos aún</td></tr>"
    th = "style='text-align:left;padding:4px 8px;border-bottom:1px solid #ccc'"
    subject = f"[Pagoya] Resumen {day:%d/%m}: {inv_deliv} entregados · {replies} respuestas · {len(demos)} demos"
    body = f"""<div style="font-family:Arial;font-size:14px;max-width:760px">
<h2>Resumen del {fmt_es(dt.datetime.combine(day, dt.time(19))).rsplit(' a las', 1)[0]}</h2>
<h3>WhatsApp</h3><ul>
<li>Invitaciones: <b>{inv_sent}</b> enviadas · <b>{inv_deliv}</b> entregadas</li>
<li>Seguimientos: {fu_sent} enviados · {fu_deliv} entregados</li>
<li>Fallidos: {failed}</li>
<li>Respuestas (personas que escribieron hoy): <b>{replies}</b></li>
<li>Calidad del número: <b style="color:{qcolor}">{quality}</b>{' — <b>ENVÍOS PAUSADOS</b>' if paused else ''}</li></ul>
<h3>Demos agendadas hoy ({len(demos)})</h3>
<table style="border-collapse:collapse"><tr><th {th}>Fecha</th><th {th}>Nombre</th><th {th}>Academia</th><th {th}>Alumnos</th><th {th}>Teléfono</th><th {th}>Origen</th></tr>{demo_rows}</table>
<h4>Próximas demos</h4><ul>{up_rows}</ul>
<h3>Contactos compartidos en conversaciones</h3><ul>{shared_html}</ul>
<h3>Conversaciones que te pasé</h3><ul>{handoff_html}</ul>
<h3>Redes sociales</h3><ul>
<li>Seguidores nuevos: Instagram {delta('ig_followers')} · Facebook {delta('fb_followers')}</li>
<li>Alcance de hoy: Instagram {metrics.get('ig_reach', '—')} · Facebook {metrics.get('fb_reach', '—')}</li>
<li>DMs recibidos: {dms}</li><li>Prospectos que llegaron por redes: {social_new}</li>
<li>Gasto de anuncios hoy: {f'${spend:,.2f} MXN' if spend is not None else 'sin campaña activa'}</li></ul>
<h3>Correo en frío</h3><ul><li>Enviados hoy: {cold}</li></ul>
<h3>Canales (hoy y últimos 30 días)</h3>
<table style="border-collapse:collapse"><tr><th {th}>Canal</th><th {th}>Hoy</th><th {th}>Prospectos 30d</th><th {th}>Demos</th><th {th}>Clientes</th></tr>{src_rows}</table>
<p><b>Recomendación:</b> {html.escape(recommendation(stats30))}</p>
<p><a href="{link('/admin', 'home')}">Abrir panel de conversaciones</a></p></div>"""
    return subject, body


def send_daily() -> str:
    subject, body = build_daily()
    send_owner(subject, body)
    return subject


def last_inbound_local(p: Prospect) -> str:
    return fmt_es(utc_naive_to_local(p.last_inbound_at)) if p.last_inbound_at else ""
