"""CLI: python -m pagoya <comando>"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import env, env_bool


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="pagoya")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="Servidor de webhooks + tareas programadas")
    pr = sub.add_parser("prospect", help="Buscar prospectos en Google Places")
    pr.add_argument("--city", action="append")
    pr.add_argument("--category", action="append")
    pr.add_argument("--no-email", action="store_true")
    t = sub.add_parser("test-whatsapp", help="Manda la invitación de prueba a tu número (OWNER_WHATSAPP)")
    t.add_argument("--template", default=None)
    sub.add_parser("chat", help="Platica con el bot en la terminal (simula un prospecto)")
    sub.add_parser("report", help="Manda el resumen diario ahora")
    sub.add_parser("report-preview", help="Guarda el resumen en reporte.html sin mandarlo")
    sub.add_parser("calendar", help="Genera y manda el calendario de la próxima semana")
    sub.add_parser("ads-propose", help="Genera propuesta de anuncios y te la manda")
    sub.add_parser("partners", help="Busca aliados y te manda la propuesta de comisión")
    sub.add_parser("site", help="Construye el sitio SEO + blog + calculadora (data/site_out/)")
    sub.add_parser("blog", help="Escribe un artículo del blog")
    sub.add_parser("templates", help="Envía las plantillas de WhatsApp a Meta para aprobación")
    sub.add_parser("quality", help="Consulta el quality rating del número")
    run = sub.add_parser("run", help="Ejecuta una tarea programada por nombre")
    run.add_argument("job")
    sub.add_parser("jobs", help="Lista tareas programadas")
    sub.add_parser("admin-link", help="Imprime el link privado a tu panel")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from .server import app
        if env_bool("ENABLE_SCHEDULER", True):
            from .scheduler import start
            start()
        uvicorn.run(app, host="0.0.0.0", port=int(env("PORT", "8000")))
    elif a.cmd == "prospect":
        from .places import run_prospecting
        print(run_prospecting(a.city, a.category, with_email=not a.no_email))
    elif a.cmd == "test-whatsapp":
        from . import whatsapp
        from .config import settings
        from .db import Prospect
        from .outreach import invitation_params, invitation_text
        from .phones import normalize_mx
        owner = normalize_mx(env("OWNER_WHATSAPP"))
        if not owner:
            sys.exit("Configura OWNER_WHATSAPP en .env")
        p = Prospect(name="Academia de Prueba", category="natación", phone=owner)
        tpl = a.template or settings()["whatsapp"]["templates"]["invitation"]
        print("Texto:", invitation_text(p))
        print("ID mensaje:", whatsapp.send_template(owner, tpl, invitation_params(p)))
        print("Contesta desde tu celular: el bot te responderá (el servidor debe estar corriendo).")
    elif a.cmd == "chat":
        chat_loop()
    elif a.cmd == "report":
        from .reports import send_daily
        print(send_daily())
    elif a.cmd == "report-preview":
        from .reports import build_daily
        subject, body = build_daily()
        open("reporte.html", "w", encoding="utf-8").write(body)
        print(subject, "-> reporte.html")
    elif a.cmd == "calendar":
        from .content import weekly_calendar_job
        print(weekly_calendar_job())
    elif a.cmd == "ads-propose":
        from .ads import propose
        print("Propuesta", propose())
    elif a.cmd == "partners":
        from .partners import build_list, draft_proposal
        print("Aliados nuevos:", build_list())
        print("Propuesta", draft_proposal())
    elif a.cmd == "site":
        from .seo import build_site
        print(build_site())
    elif a.cmd == "blog":
        from .seo import write_blog_post
        print(write_blog_post())
    elif a.cmd == "templates":
        from .templates import submit_all
        print(json.dumps(submit_all(), ensure_ascii=False, indent=1))
    elif a.cmd == "quality":
        from .outreach import check_quality
        print(check_quality())
    elif a.cmd == "admin-link":
        from .approvals import link
        print(link("/admin", "home"))
    elif a.cmd in ("run", "jobs"):
        from .scheduler import jobs
        js = {n: fn for n, fn, _ in jobs()}
        if a.cmd == "jobs":
            for n, _, c in jobs():
                print(f"{n:32s} {c}")
        else:
            print(js[a.job]())


def chat_loop():
    """Simulador local del bot (usa la BD local, no manda WhatsApp)."""
    from . import bot
    from .db import Message, Prospect, session
    with session() as s:
        p = Prospect(name="Academia Delfines", category="natación", city="Monterrey",
                     phone=None, source="Simulación")
        s.add(p)
        s.flush()
        pid = p.id
    print("Escribe como si fueras el prospecto (Ctrl+C para salir).")
    while True:
        try:
            text = input("Tú: ")
        except (EOFError, KeyboardInterrupt):
            break
        with session() as s:
            p = s.get(Prospect, pid)
            s.add(Message(prospect_id=pid, channel="whatsapp", direction="in", body=text))
            s.flush()
            reply, out = bot.handle_inbound(s, p, "whatsapp", text)
            if reply:
                s.add(Message(prospect_id=pid, channel="whatsapp", direction="out", body=reply))
            print("Bot:", reply or f"(sin respuesta; estado={p.status}, pausado={p.bot_paused})")


if __name__ == "__main__":
    main()
