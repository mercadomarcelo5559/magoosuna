"""Servidor: webhooks (WhatsApp, Instagram/Facebook, Stripe), calculadora, aprobaciones y panel."""
from __future__ import annotations

import html
import logging
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from . import approvals, outreach, social, whatsapp
from .config import ROOT, env, settings
from .db import Approval, Message, Prospect, find_prospect, kv_set, session, utcnow
from .phones import normalize_mx
from .seo import calc_loss

log = logging.getLogger(__name__)
app = FastAPI(title="Pagoya Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST", "GET"], allow_headers=["*"])
(ROOT / "data" / "generated").mkdir(parents=True, exist_ok=True)
app.mount("/media/generated", StaticFiles(directory=ROOT / "data" / "generated"), name="generated")
app.mount("/media", StaticFiles(directory=ROOT / "media"), name="media")
(ROOT / "data" / "site_out").mkdir(parents=True, exist_ok=True)
app.mount("/sitio", StaticFiles(directory=ROOT / "data" / "site_out", html=True), name="sitio")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,Arial;max-width:760px;margin:0 auto;padding:16px;color:#1d2433;background:#fff}}
.in{{background:#eef2f7;padding:8px 12px;border-radius:10px;margin:6px 40px 6px 0}}
.out{{background:#dcf8c6;padding:8px 12px;border-radius:10px;margin:6px 0 6px 40px}}
textarea{{width:100%;min-height:90px;font:inherit}}button{{padding:10px 16px;font:inherit}}small{{color:#666}}</style>
</head><body>{body}</body></html>""")


@app.get("/health")
def health():
    return {"ok": True}


# ---------------- WhatsApp ----------------

@app.get("/webhooks/whatsapp")
def wa_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == env("WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhooks/whatsapp")
async def wa_webhook(request: Request, bg: BackgroundTasks):
    body = await request.body()
    if not whatsapp.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401)
    bg.add_task(outreach.process_webhook, await request.json())
    return {"ok": True}


# ---------------- Instagram / Facebook ----------------

@app.get("/webhooks/meta")
def meta_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == env("META_VERIFY_TOKEN"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhooks/meta")
async def meta_webhook(request: Request, bg: BackgroundTasks):
    body = await request.body()
    if not whatsapp.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401)
    bg.add_task(social.process_webhook, await request.json())
    return {"ok": True}


# ---------------- Stripe ----------------

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, bg: BackgroundTasks):
    from . import referrals
    body = await request.body()
    if not referrals.verify_stripe(body, request.headers.get("stripe-signature", "")):
        raise HTTPException(400, "firma inválida")
    bg.add_task(referrals.handle_stripe_event, await request.json())
    return {"ok": True}


# ---------------- Calculadora ----------------

class Lead(BaseModel):
    students: int
    fee: float
    late: float
    name: str
    academy: str
    whatsapp: str
    consent: bool = False
    page: str = ""


@app.post("/api/lead")
def lead(data: Lead, bg: BackgroundTasks):
    phone = normalize_mx(data.whatsapp)
    if not phone:
        raise HTTPException(422, "Número de WhatsApp inválido (10 dígitos)")
    if not data.consent:
        raise HTTPException(422, "Necesitamos tu autorización para escribirte")
    calc = calc_loss(data.students, data.fee, data.late)
    with session() as s:
        p = find_prospect(s, phone=phone)
        if not p:
            p = Prospect(phone=phone, phone_kind="mobile", source="Calculadora")
            s.add(p)
        if p.do_not_contact:
            return {"calc": calc}  # pidió baja antes: le mostramos su resultado, pero no le escribimos
        p.name = p.name or data.academy[:200]
        p.contact_name = data.name[:200]
        p.students = data.students or p.students
        p.monthly_fee = data.fee
        p.hot = True
        p.notes = ((p.notes or "") + f"\ncalculadora: pérdida_anual={calc['perdida_anual']:,} atraso={data.late}%").strip()
        if p.invited_at is None:
            bg.add_task(outreach.contact_hot_leads)
    return {"calc": calc}


# ---------------- Referidos / baja de correo ----------------

@app.get("/r/{code}")
def referral_redirect(code: str):
    text = f"Hola, vengo recomendado (código {code.upper()}) y quiero conocer Pagoya"
    return RedirectResponse(f"https://wa.me/{env('WHATSAPP_PUBLIC_NUMBER')}?text={quote(text)}")


@app.api_route("/baja/email/{email}", methods=["GET", "POST"])
def email_unsubscribe(email: str, t: str = ""):
    if not approvals.check(t, f"/baja/email/{email}", "unsub", email):
        raise HTTPException(403)
    from .coldemail import unsubscribe
    unsubscribe(email)
    return _page("Baja", "<h2>Listo, no volverás a recibir correos de Pagoya.</h2>")


# ---------------- Aprobaciones ----------------

def _check(t: str, path: str, *parts):
    if not approvals.check(t, path, *parts):
        raise HTTPException(403, "Link inválido")


@app.get("/approve/{kind}/{ref}")
def approve(kind: str, ref: str, t: str, bg: BackgroundTasks):
    path = f"/approve/{kind}/{ref}"
    if kind == "calendar":
        _check(t, path, "calendar", ref)
        from .content import approve_week
        approve_week(ref)
        return _page("Aprobado", f"<h2>Calendario {html.escape(ref)} aprobado. Se publicará en su horario.</h2>")
    _check(t, path, kind, int(ref))
    with session() as s:
        ap = s.get(Approval, int(ref))
        if not ap or ap.status not in ("pending", "changes"):
            return _page("Ya decidido", "<h2>Esto ya fue decidido antes.</h2>")
        ap.status, ap.decided_at = "approved", utcnow()
    if kind == "ads":
        from .ads import launch

        def _launch():
            try:
                camp = launch(int(ref))
                from .notify import owner_alert
                owner_alert("Campaña lanzada", f"Campaña {camp} activa en Meta.")
            except Exception as e:  # noqa: BLE001
                from .notify import owner_alert
                owner_alert("No se pudo lanzar la campaña", str(e))
        bg.add_task(_launch)
        return _page("Aprobado", "<h2>Aprobado. Estoy creando la campaña; te aviso por correo.</h2>")
    if kind == "review_reply":
        from .gbp import approve_reply
        approve_reply(int(ref))
    return _page("Aprobado", "<h2>Aprobado ✅</h2>")


@app.get("/reject/{kind}/{ref}")
def reject(kind: str, ref: str, t: str):
    _check(t, f"/reject/{kind}/{ref}", kind, int(ref))
    with session() as s:
        ap = s.get(Approval, int(ref))
        ap.status, ap.decided_at = "rejected", utcnow()
    return _page("Rechazado", "<h2>Rechazado. No se gastó nada.</h2>")


@app.get("/changes/{kind}/{ref}")
def changes_form(kind: str, ref: str, t: str):
    parts = (kind, ref) if kind == "calendar" else (kind, int(ref))
    _check(t, f"/changes/{kind}/{ref}", *parts)
    label = "Escribe la respuesta exacta a publicar" if kind == "review_reply" else "¿Qué cambios quieres?"
    return _page("Cambios", f"""<h2>{label}</h2><form method="post">
<input type="hidden" name="t" value="{html.escape(t)}"><textarea name="feedback" required></textarea>
<p><button>Enviar</button></p></form>""")


@app.post("/changes/{kind}/{ref}")
def changes_submit(kind: str, ref: str, bg: BackgroundTasks, t: str = Form(...), feedback: str = Form(...)):
    parts = (kind, ref) if kind == "calendar" else (kind, int(ref))
    _check(t, f"/changes/{kind}/{ref}", *parts)
    if kind == "calendar":
        from .content import apply_changes
        with session() as s:
            ap = s.scalar(select(Approval).where(Approval.kind == "calendar", Approval.ref == ref))
            if ap:
                ap.status, ap.feedback = "changes", feedback
        bg.add_task(apply_changes, ref, feedback)
        return _page("Recibido", "<h2>Recibido. Te mando la versión corregida por correo; no publico nada "
                                 "hasta que la apruebes.</h2>")
    if kind == "review_reply":
        from .gbp import approve_reply
        approve_reply(int(ref), feedback)
        return _page("Publicado", "<h2>Respuesta publicada.</h2>")
    if kind == "partners":
        with session() as s:
            ap = s.get(Approval, int(ref))
            ap.status, ap.feedback = "changes", feedback
        from .partners import draft_proposal
        bg.add_task(draft_proposal)
        return _page("Recibido", "<h2>Recibido. Te mando una nueva versión.</h2>")
    raise HTTPException(404)


@app.get("/admin/resume")
def resume_sending(t: str):
    _check(t, "/admin/resume", "resume")
    with session() as s:
        kv_set(s, "wa_paused", {"paused": False, "at": utcnow().isoformat()})
    return _page("Reanudado", "<h2>Envíos reanudados.</h2>")


# ---------------- Panel de conversaciones ----------------

@app.get("/admin/chat/{pid}")
def chat_view(pid: int, t: str):
    _check(t, f"/admin/chat/{pid}", pid)
    with session() as s:
        p = s.get(Prospect, pid)
        if not p:
            raise HTTPException(404)
        msgs = list(s.scalars(select(Message).where(Message.prospect_id == pid).order_by(Message.id)))
        bubbles = "".join(
            f"<div class='{'in' if m.direction == 'in' else 'out'}'>{html.escape(m.body)}"
            f"<br><small>{m.channel} · {m.created_at:%d/%m %H:%M} UTC {m.status}</small></div>" for m in msgs)
        info = (f"<h2>{html.escape(p.name or p.contact_name or '')}</h2><p>{html.escape(p.phone or '')} · "
                f"{html.escape(p.category)} · {html.escape(p.city)} · alumnos: {p.students or '¿?'} · "
                f"estado: <b>{p.status}</b> · origen: {p.source} · bot: {'en pausa' if p.bot_paused else 'activo'}</p>")
    return _page("Conversación", f"""{info}{bubbles}
<form method="post" action="/admin/chat/{pid}/send"><input type="hidden" name="t" value="{html.escape(t)}">
<textarea name="text" placeholder="Tu respuesta (WhatsApp solo permite texto libre si te escribió en las últimas 24 h)"></textarea>
<p><button name="action" value="send">Enviar</button> <button name="action" value="resume">Reactivar bot</button>
<button name="action" value="client">Marcar como cliente</button> <button name="action" value="lost">Marcar perdido</button></p></form>""")


@app.post("/admin/chat/{pid}/send")
def chat_send(pid: int, t: str = Form(...), text: str = Form(""), action: str = Form("send")):
    _check(t, f"/admin/chat/{pid}", pid)
    if action == "send" and text.strip():
        try:
            outreach.manual_send(pid, text.strip())
        except Exception as e:  # noqa: BLE001
            return _page("Error", f"<p>No se pudo enviar: {html.escape(str(e))}</p>")
    elif action == "resume":
        with session() as s:
            s.get(Prospect, pid).bot_paused = False
    elif action == "client":
        from .referrals import on_new_client
        on_new_client(pid)
    elif action == "lost":
        with session() as s:
            s.get(Prospect, pid).advance("perdido")
    return RedirectResponse(f"/admin/chat/{pid}?t={t}", status_code=303)


@app.get("/admin")
def admin_home(t: str):
    _check(t, "/admin", "home")
    from .db import STATUSES
    from sqlalchemy import func
    with session() as s:
        counts = dict(s.execute(select(Prospect.status, func.count()).group_by(Prospect.status)).all())
        recent = list(s.scalars(select(Prospect).where(Prospect.last_inbound_at.is_not(None))
                                .order_by(Prospect.last_inbound_at.desc()).limit(40)))
        rows = "".join(
            f"<li><a href='{approvals.link(f'/admin/chat/{p.id}', p.id)}'>{html.escape(p.name or p.contact_name or p.phone or '')}"
            f"</a> — {p.status}{' · 🙋 contigo' if p.bot_paused else ''}</li>" for p in recent)
    funnel = " · ".join(f"{st}: {counts.get(st, 0)}" for st in STATUSES)
    return _page("Panel Pagoya", f"<h2>CRM</h2><p>{funnel}</p><h3>Conversaciones recientes</h3><ul>{rows}</ul>"
                                 f"<p><small>Zona: {settings()['timezone']}</small></p>")
