"""Tareas programadas (hora de Monterrey). Corre dentro del servidor (ENABLE_SCHEDULER=true)."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings

log = logging.getLogger(__name__)


# En TEST_MODE estas tareas masivas no corren (si no, te llegarían 60 invitaciones a tu número).
SKIP_IN_TEST = {"invitaciones", "seguimientos", "clientes_referidos_reseñas", "correo_frio", "aliados_contacto",
                "recordatorios_demo"}


def _safe(name, fn):
    def run():
        from .config import test_mode
        if test_mode() and name in SKIP_IN_TEST:
            return
        try:
            log.info("Tarea %s: %s", name, fn())
        except Exception:  # noqa: BLE001
            log.exception("Tarea %s falló", name)
            try:
                from .notify import owner_alert
                owner_alert(f"Falló la tarea {name}", "Revisa los logs del servidor.")
            except Exception:  # noqa: BLE001
                pass
    run.__name__ = name
    return run


def jobs() -> list[tuple[str, callable, dict]]:
    from . import (ads, coldemail, content, gbp, outreach, partners, places, reports, seo)
    cfg = settings()
    rh, rm = cfg["report"]["time"].split(":")
    blog_days = ",".join(str(d) for d in cfg["seo"]["blog_days"])
    cs = cfg["social"]["calendar_send"]
    cd = cfg["social"]["calendar_deadline"]
    dow = lambda d: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][d]  # noqa: E731
    return [
        # WhatsApp
        ("invitaciones", outreach.run_invitations, dict(day_of_week="mon-fri", hour="10-19", minute="*/10")),
        ("seguimientos", outreach.run_followups, dict(day_of_week="mon-fri", hour="11-12", minute="5,35")),
        ("calidad", outreach.check_quality, dict(hour="8-20", minute="*/30")),
        ("prospectos_calientes", outreach.contact_hot_leads, dict(minute="*")),
        ("recordatorios_demo", outreach.run_demo_reminders, dict(minute="*/15")),
        ("clientes_referidos_reseñas", outreach.run_client_nudges, dict(day_of_week="mon-sat", hour="12", minute="0")),
        # Prospección (de noche para tener lista fresca)
        ("prospeccion", places.run_prospecting, dict(day_of_week="sun", hour="2", minute="0")),
        # Reportes
        ("resumen_diario", reports.send_daily, dict(hour=rh, minute=rm)),
        # Redes
        ("calendario_semanal", content.weekly_calendar_job, dict(day_of_week=dow(cs["weekday"]),
                                                                  hour=cs["time"].split(":")[0],
                                                                  minute=cs["time"].split(":")[1])),
        ("revisa_respuestas_calendario", content.check_calendar_replies, dict(minute="*/20")),
        ("aprobacion_lunes", content.deadline_job, dict(day_of_week=dow(cd["weekday"]),
                                                        hour=cd["time"].split(":")[0], minute=cd["time"].split(":")[1])),
        ("publicar", content.publish_due, dict(minute="*/5")),
        ("propuesta_anuncios", ads.propose, dict(day="1", hour="9", minute="30")),
        # Canales extra
        ("seo_blog", seo.weekly_seo_job, dict(day_of_week=blog_days, hour="7", minute="0")),
        ("google_business_post", gbp.weekly_post, dict(day_of_week="tue", hour="11", minute="0")),
        ("google_business_reseñas", gbp.check_reviews, dict(hour="9-20", minute="15")),
        ("correo_frio", coldemail.run_cold_email, dict(day_of_week="mon-fri", hour="9-13", minute="20")),
        ("correo_frio_respuestas", coldemail.check_replies, dict(minute="*/15")),
        ("aliados_contacto", partners.contact_partners, dict(day_of_week="mon-fri", hour="10", minute="45")),
    ]


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=settings()["timezone"])
    for name, fn, cron in jobs():
        sched.add_job(_safe(name, fn), CronTrigger(timezone=settings()["timezone"], **cron), id=name,
                      max_instances=1, coalesce=True, misfire_grace_time=600)
    sched.start()
    log.info("Programador iniciado con %d tareas", len(sched.get_jobs()))
    return sched
