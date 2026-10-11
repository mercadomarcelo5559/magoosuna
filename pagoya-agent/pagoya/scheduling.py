"""Horarios de demo: lunes a sábado 10:00-18:00 (Monterrey), sin empalmes."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from .config import settings
from .db import Demo
from .timeutil import hm, local_naive


def available_slots(s, days_ahead: int | None = None, now: dt.datetime | None = None,
                    limit: int = 12) -> list[dt.datetime]:
    cfg = settings()["demos"]
    now = now or local_naive()
    earliest = now + dt.timedelta(hours=cfg["min_notice_hours"])
    dur = dt.timedelta(minutes=cfg["duration_minutes"])
    taken = [(d.start_local, d.start_local + dt.timedelta(minutes=d.duration))
             for d in s.scalars(select(Demo).where(Demo.cancelled.is_(False),
                                                   Demo.start_local >= now - dt.timedelta(days=1)))]
    out = []
    for i in range((days_ahead or cfg["days_ahead"]) + 1):
        day = (now + dt.timedelta(days=i)).date()
        if day.weekday() not in cfg["days"]:
            continue
        t = dt.datetime.combine(day, hm(cfg["start"]))
        end = dt.datetime.combine(day, hm(cfg["end"]))
        while t + dur <= end:
            if t >= earliest and not any(a < t + dur and t < b for a, b in taken):
                out.append(t)
            t += dur
    # repartir: no ofrecer 12 horarios del mismo día
    spread, per_day = [], {}
    for t in out:
        if per_day.get(t.date(), 0) < 3 and (t.minute == 0 or per_day.get(t.date(), 0) == 0):
            spread.append(t)
            per_day[t.date()] = per_day.get(t.date(), 0) + 1
    return (spread or out)[:limit]


def is_valid_slot(s, start: dt.datetime) -> tuple[bool, str]:
    cfg = settings()["demos"]
    now = local_naive()
    dur = dt.timedelta(minutes=cfg["duration_minutes"])
    if start.weekday() not in cfg["days"]:
        return False, "Las demos son de lunes a sábado."
    if start.time() < hm(cfg["start"]) or (start + dur).time() > hm(cfg["end"]) or \
            (start + dur).date() != start.date():
        return False, f"El horario de demos es de {cfg['start']} a {cfg['end']} (hora de Monterrey)."
    if start < now + dt.timedelta(hours=cfg["min_notice_hours"]):
        return False, f"Necesitamos al menos {cfg['min_notice_hours']} horas de anticipación."
    for d in s.scalars(select(Demo).where(Demo.cancelled.is_(False))):
        if d.start_local < start + dur and start < d.start_local + dt.timedelta(minutes=d.duration):
            return False, "Ese horario ya está ocupado."
    return True, ""
