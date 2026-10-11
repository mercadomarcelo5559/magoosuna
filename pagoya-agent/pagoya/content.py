"""Calendario semanal de redes: genera, manda por correo, espera cambios y publica."""
from __future__ import annotations

import datetime as dt
import html
import logging
import random
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from . import llm, mailer, social
from .approvals import link
from .config import ROOT, env, public_url, settings
from .db import Approval, ContentItem, session, utcnow
from .timeutil import DIAS, hm, local_naive

log = logging.getLogger(__name__)
MEDIA = ROOT / "media"
GEN = ROOT / "data" / "generated"  # en el disco persistente
LIBRARY = MEDIA / "library"
FONT_DIRS = [ROOT.parent / "worker" / "fonts", Path("/usr/share/fonts")]

# Clips de la app que grabas una vez (pantalla del celular) y el sistema reutiliza.
APP_CLIPS = {
    "recordatorio_whatsapp": "Recordatorio automático por WhatsApp",
    "pago_oxxo": "Pago con OXXO / tarjeta",
    "panel_dueno": "Panel del dueño",
}

CAL_SYSTEM = """Eres el community manager de Pagoya (software de cobranza automática para academias y negocios con mensualidades en México: recordatorios por WhatsApp, pagos con tarjeta y OXXO, panel del dueño, configuración gratis cargando su lista de alumnos).
Público: dueños de academias de natación, idiomas, música, artes marciales, gimnasia, guarderías, gimnasios, crossfit, box, pilates, yoga, baile y clubes de pádel/tenis en Monterrey, Saltillo y alrededores.
Escribe en español de México, cercano y directo. Cada copy termina con un llamado a la acción para escribir por WhatsApp o mandar DM para agendar demo."""


def week_key(monday: dt.date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def next_monday(today: dt.date | None = None) -> dt.date:
    today = today or local_naive().date()
    return today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)


def testimonials() -> list[dict]:
    path = ROOT / "config" / "testimonials.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [t for t in data if t.get("permiso") is True]


def _font(size: int):
    for d in FONT_DIRS:
        for f in sorted(d.rglob("*.ttf")) if d.exists() else []:
            try:
                return ImageFont.truetype(str(f), size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def media_path(rel: str) -> Path:
    return GEN / rel.split("/", 1)[1] if rel.startswith("generated/") else MEDIA / rel


def render_card(text: str, kind: str, name: str) -> str:
    """Imagen simple de marca (1080x1350 post, 1080x1920 historia). Devuelve ruta relativa a /media."""
    GEN.mkdir(parents=True, exist_ok=True)
    w, h = (1080, 1920) if kind == "story" else (1080, 1350)
    bg = random.choice([(15, 82, 186), (0, 133, 119), (33, 37, 41), (106, 27, 154)])
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    big = _font(84)
    y = h // 3
    for line in textwrap.wrap(text, 20)[:7]:
        tw = d.textlength(line, font=big)
        d.text(((w - tw) / 2, y), line, font=big, fill="white")
        y += 105
    small = _font(48)
    foot = "pagoya.com.mx · Agenda tu demo por WhatsApp"
    d.text(((w - d.textlength(foot, font=small)) / 2, h - 170), foot, font=small, fill=(255, 220, 90))
    out = GEN / f"{name}.jpg"
    img.save(out, quality=92)
    return f"generated/{out.name}"


def generate_week(monday: dt.date, feedback: str = "") -> str:
    cfg = settings()["social"]
    wk = week_key(monday)
    tests = testimonials()
    clips = {k: v for k, v in APP_CLIPS.items() if (LIBRARY / f"{k}.mp4").exists()}
    prompt = f"""Genera el calendario de la semana que inicia el lunes {monday:%Y-%m-%d}.
- 4 publicaciones: lunes, miércoles, viernes y sábado. Mezcla: reels cortos mostrando la app, tips de cobranza para academias, {'casos de éxito (usa SOLO estos testimonios autorizados: ' + yaml.safe_dump(tests, allow_unicode=True) + ')' if tests else 'NO hay casos de éxito autorizados todavía: no inventes ninguno'}, y promoción de configuración gratis.
- Al menos 2 deben ser reels. Clips de la app disponibles para reels: {list(clips) or 'ninguno todavía (los reels se publicarán como imagen mientras tanto)'}; elige uno en "clip" ({list(APP_CLIPS)}).
- 7 historias (lunes a domingo), una por día: frases cortas, encuestas o tips.
{('- Cambios que pidió Marcelo sobre la versión anterior: ' + feedback) if feedback else ''}

JSON: {{"items": [{{"dia": 0-6 (0=lunes), "tipo": "reel"|"post"|"story", "pilar": "app"|"tip"|"caso"|"promo",
"titulo": "...", "texto_imagen": "frase de máximo 12 palabras para la imagen",
"caption": "copy completo (vacío para historias)", "hashtags": "#... (8 a 12, vacío para historias)",
"guion": "guion del reel por escenas con tiempos (solo reels)", "clip": "nombre del clip o vacío"}}]}}"""
    data = llm.ask_json(CAL_SYSTEM, prompt)
    with session() as s:
        for old in s.scalars(select(ContentItem).where(ContentItem.week == wk,
                                                       ContentItem.status.in_(("draft", "hold")))):
            s.delete(old)
        for i, it in enumerate(data["items"]):
            day = monday + dt.timedelta(days=int(it["dia"]))
            kind = it["tipo"] if it["tipo"] in ("reel", "post", "story") else "post"
            at = dt.datetime.combine(day, hm(cfg["story_time"] if kind == "story" else cfg["post_time"]))
            media = ""
            clip = (it.get("clip") or "").strip()
            if kind == "reel" and clip in clips:
                media = f"library/{clip}.mp4"
            else:
                media = render_card(it.get("texto_imagen") or it.get("titulo", ""), kind, f"{wk}-{i}")
            s.add(ContentItem(week=wk, kind=kind, pillar=it.get("pilar", ""), publish_at_local=at,
                              title=it.get("titulo", "")[:200], caption=it.get("caption", ""),
                              hashtags=it.get("hashtags", ""), script=it.get("guion", ""),
                              image_text=it.get("texto_imagen", ""), media_file=media, status="draft"))
        ap = s.scalar(select(Approval).where(Approval.kind == "calendar", Approval.ref == wk))
        if not ap:
            ap = Approval(kind="calendar", ref=wk)
            s.add(ap)
        ap.status = "pending"
        ap.payload = {"needs_explicit_ok": bool(feedback)}
    return wk


def email_calendar(wk: str, revised: bool = False) -> None:
    with session() as s:
        items = list(s.scalars(select(ContentItem).where(ContentItem.week == wk)
                               .order_by(ContentItem.publish_at_local)))
        rows = []
        for it in items:
            img = public_url(f"/media/{it.media_file}") if it.media_file else ""
            rows.append(f"""<tr><td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd">
<b>{DIAS[it.publish_at_local.weekday()].capitalize()} {it.publish_at_local:%H:%M}</b><br>{it.kind.upper()} · {it.pillar}</td>
<td style="padding:8px;border-bottom:1px solid #ddd"><b>{html.escape(it.title)}</b><br>
{html.escape(it.caption).replace(chr(10), '<br>')}<br><i>{html.escape(it.hashtags)}</i>
{('<pre style="white-space:pre-wrap;background:#f6f6f6;padding:6px">' + html.escape(it.script) + '</pre>') if it.script else ''}
{f'<br><a href="{img}">ver imagen/video</a>' if img else ''}</td></tr>""")
    approve = link(f"/approve/calendar/{wk}", "calendar", wk)
    changes = link(f"/changes/calendar/{wk}", "calendar", wk)
    deadline = "" if revised else (
        "<p><b>Si no me respondes con cambios antes del lunes a las 9:00 am, lo publico tal cual.</b> "
        "Para pedir cambios responde a este correo o usa el botón.</p>")
    mailer.send_owner(
        f"[Pagoya] Calendario de redes {wk}{' (versión corregida)' if revised else ''}",
        f"""<h2>Calendario {wk}</h2>{deadline}
<p><a href="{approve}">✅ Aprobar y publicar</a> &nbsp; | &nbsp; <a href="{changes}">✏️ Pedir cambios</a></p>
<table style="border-collapse:collapse;font-family:Arial;font-size:14px">{''.join(rows)}</table>""")


def weekly_calendar_job() -> str:
    wk = generate_week(next_monday())
    email_calendar(wk)
    return wk


def apply_changes(wk: str, feedback: str) -> None:
    monday = dt.date.fromisocalendar(int(wk[:4]), int(wk[6:]), 1)
    generate_week(monday, feedback)
    email_calendar(wk, revised=True)


def approve_week(wk: str) -> None:
    with session() as s:
        ap = s.scalar(select(Approval).where(Approval.kind == "calendar", Approval.ref == wk))
        if ap:
            ap.status, ap.decided_at = "approved", utcnow()
        for it in s.scalars(select(ContentItem).where(ContentItem.week == wk, ContentItem.status == "draft")):
            it.status = "approved"


def check_calendar_replies() -> None:
    """Lee respuestas de Marcelo al correo del calendario (Gmail IMAP)."""
    since = (local_naive() - dt.timedelta(days=3)).strftime("%d-%b-%Y")
    try:
        mails = mailer.fetch_unseen("imap.gmail.com", env("GMAIL_USER"), env("GMAIL_APP_PASSWORD"),
                                    since=since, subject_contains="Calendario de redes")
    except Exception as e:  # noqa: BLE001
        log.warning("IMAP Gmail falló: %s", e)
        return
    for m in mails:
        if m["from"] != env("OWNER_EMAIL").lower():
            continue
        wk = next((w for w in m["subject"].split() if "-W" in w), None)
        body = mailer.strip_quoted(m["body"])
        if not wk or not body:
            continue
        wk = wk.strip("()")
        if body.strip().lower().rstrip(".!") in ("ok", "aprobado", "va", "sí", "si", "dale", "publica"):
            approve_week(wk)
        else:
            with session() as s:
                ap = s.scalar(select(Approval).where(Approval.kind == "calendar", Approval.ref == wk))
                if ap:
                    ap.status, ap.feedback = "changes", body[:4000]
            apply_changes(wk, body)


def deadline_job() -> None:
    """Lunes 9:00: si no hubo cambios, se aprueba solo."""
    check_calendar_replies()
    wk = week_key(local_naive().date() - dt.timedelta(days=local_naive().weekday()))
    with session() as s:
        ap = s.scalar(select(Approval).where(Approval.kind == "calendar", Approval.ref == wk))
        auto = ap and ap.status == "pending" and not (ap.payload or {}).get("needs_explicit_ok")
    if auto:
        approve_week(wk)
        log.info("Calendario %s aprobado automáticamente", wk)


def publish_due() -> int:
    now = local_naive()
    n = 0
    with session() as s:
        due = list(s.scalars(select(ContentItem).where(ContentItem.status == "approved",
                                                       ContentItem.publish_at_local <= now)))
        for it in due:
            if not social.configured():
                it.status, it.result = "failed", "Meta no configurado"
                continue
            if it.media_file.startswith("generated/") and not media_path(it.media_file).exists():
                render_card(it.image_text or it.title, it.kind, Path(it.media_file).stem)
            url = public_url(f"/media/{it.media_file}")
            caption = f"{it.caption}\n\n{it.hashtags}".strip()
            kind = it.kind if it.media_file.endswith(".mp4") or it.kind == "story" else "post"
            res = []
            for name, fn in (("ig", social.publish_instagram), ("fb", social.publish_facebook)):
                try:
                    res.append(f"{name}:{fn(kind, url, caption)}")
                except Exception as e:  # noqa: BLE001
                    res.append(f"{name}:ERROR {e}")
            it.result = " | ".join(res)
            it.status = "published" if any("ERROR" not in r for r in res) else "failed"
            n += 1
    return n

