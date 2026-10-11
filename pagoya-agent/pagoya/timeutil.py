import datetime as dt
from zoneinfo import ZoneInfo

from .config import settings


def tz() -> ZoneInfo:
    return ZoneInfo(settings().get("timezone", "America/Monterrey"))


def now_local() -> dt.datetime:
    return dt.datetime.now(tz())


def local_naive(d: dt.datetime | None = None) -> dt.datetime:
    return (d or now_local()).astimezone(tz()).replace(tzinfo=None)


def to_utc_naive(local: dt.datetime) -> dt.datetime:
    if local.tzinfo is None:
        local = local.replace(tzinfo=tz())
    return local.astimezone(dt.timezone.utc).replace(tzinfo=None)


def utc_naive_to_local(u: dt.datetime) -> dt.datetime:
    return u.replace(tzinfo=dt.timezone.utc).astimezone(tz()).replace(tzinfo=None)


def hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def local_day_bounds_utc(day: dt.date | None = None) -> tuple[dt.datetime, dt.datetime]:
    day = day or now_local().date()
    start = dt.datetime.combine(day, dt.time(0, 0))
    return to_utc_naive(start), to_utc_naive(start + dt.timedelta(days=1))


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fmt_es(d: dt.datetime) -> str:
    h = d.strftime("%I:%M").lstrip("0")
    ampm = "am" if d.hour < 12 else "pm"
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} a las {h} {ampm}"
