"""Prospección con Google Places API (New) - Text Search."""
from __future__ import annotations

import logging
import re
import time

import httpx
from sqlalchemy import select

from .config import env, settings
from .db import Partner, Prospect, session
from .phones import normalize_mx, phone_kind

log = logging.getLogger(__name__)

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.nationalPhoneNumber",
    "places.internationalPhoneNumber", "places.websiteUri", "places.rating", "places.userRatingCount",
    "places.businessStatus", "nextPageToken",
])
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BAD_EMAIL = ("example.", "sentry", "wixpress", ".png", ".jpg", ".webp", "@2x", "domain.com", "u003e")


def search(query: str, max_pages: int = 3) -> list[dict]:
    key = env("GOOGLE_PLACES_API_KEY")
    if not key:
        raise RuntimeError("Falta GOOGLE_PLACES_API_KEY")
    out, token = [], None
    for _ in range(max_pages):
        body = {"textQuery": query, "languageCode": "es", "regionCode": "MX", "pageSize": 20}
        if token:
            body["pageToken"] = token
        r = httpx.post(URL, json=body, timeout=30,
                       headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS})
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(2)
    return out


def find_public_email(website: str) -> str | None:
    """Busca un correo público en la página del negocio (inicio y /contacto)."""
    if not website:
        return None
    base = website.rstrip("/")
    for path in ("", "/contacto", "/contact", "/contactanos"):
        try:
            r = httpx.get(base + path, timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (PagoyaBot; +https://www.pagoya.com.mx)"})
            if r.status_code != 200:
                continue
            for m in EMAIL_RE.findall(r.text):
                e = m.lower().strip(".")
                if not any(b in e for b in BAD_EMAIL):
                    return e
        except httpx.HTTPError:
            continue
    return None


def upsert_place(s, place: dict, category: str, city: str, with_email: bool) -> str:
    """Devuelve 'new', 'dup' o 'skip'."""
    if place.get("businessStatus") not in (None, "OPERATIONAL"):
        return "skip"
    pid = place["id"]
    if s.scalar(select(Prospect.id).where(Prospect.place_id == pid)):
        return "dup"
    raw = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
    phone = normalize_mx(raw)
    website = place.get("websiteUri", "") or ""
    if phone and s.scalar(select(Prospect.id).where(Prospect.phone == phone)):
        return "dup"  # misma persona, otra ficha
    kind = phone_kind(phone) if phone else "unknown"
    email = find_public_email(website) if with_email and website else None
    if email and s.scalar(select(Prospect.id).where(Prospect.email == email)):
        email = None
    if not phone and not email:
        return "skip"
    if kind == "fixed" and not email:
        return "skip"  # fijo confirmado: no tiene WhatsApp y no hay otro canal
    s.add(Prospect(
        name=place.get("displayName", {}).get("text", "")[:200], category=category, city=city,
        address=place.get("formattedAddress", "")[:300],
        phone=phone if kind != "fixed" else None, raw_phone=raw, phone_kind=kind,
        email=email, website=website[:300], rating=place.get("rating"),
        reviews=place.get("userRatingCount"), place_id=pid, source="Google Places",
    ))
    return "new"


def run_prospecting(cities: list[str] | None = None, categories: list[str] | None = None,
                    with_email: bool = True) -> dict:
    cfg = settings()["prospecting"]
    cities = cities or cfg["cities"]
    cats = cfg["categories"]
    stats = {"new": 0, "dup": 0, "skip": 0, "queries": 0}
    for city in cities:
        for category, terms in cats.items():
            if categories and category not in categories:
                continue
            for term in terms:
                try:
                    places = search(f"{term} en {city}", cfg.get("max_pages_per_query", 3))
                except Exception as e:  # noqa: BLE001
                    log.warning("Places falló %s/%s: %s", city, term, e)
                    continue
                stats["queries"] += 1
                with session() as s:
                    for pl in places:
                        if (pl.get("userRatingCount") or 0) < cfg.get("min_reviews", 0):
                            stats["skip"] += 1
                            continue
                        stats[upsert_place(s, pl, category, city.split(",")[0], with_email)] += 1
                        s.flush()
    log.info("Prospección: %s", stats)
    return stats


PARTNER_QUERIES = {
    "contador": ["despacho contable", "contador público"],
    "liga/federación": ["liga deportiva", "asociación deportiva", "federación de natación",
                        "liga de futbol infantil"],
    "escuela de entrenadores": ["escuela de entrenadores deportivos", "certificación entrenador personal"],
    "uniformes y equipo": ["uniformes deportivos", "tienda de artículos deportivos", "equipo de artes marciales"],
}


def run_partner_search(cities: list[str] | None = None) -> int:
    cities = cities or settings()["prospecting"]["cities"][:6]
    added = 0
    for city in cities:
        for kind, terms in PARTNER_QUERIES.items():
            for term in terms:
                try:
                    places = search(f"{term} en {city}", 1)
                except Exception as e:  # noqa: BLE001
                    log.warning("Places aliados falló: %s", e)
                    continue
                with session() as s:
                    for pl in places:
                        if s.scalar(select(Partner.id).where(Partner.place_id == pl["id"])):
                            continue
                        web = pl.get("websiteUri", "") or ""
                        s.add(Partner(name=pl.get("displayName", {}).get("text", "")[:200], kind=kind,
                                      city=city.split(",")[0],
                                      phone=normalize_mx(pl.get("internationalPhoneNumber")) or "",
                                      website=web[:300], email=find_public_email(web) or "",
                                      place_id=pl["id"]))
                        added += 1
    return added
