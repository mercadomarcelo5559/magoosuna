"""Anuncios en Meta (Click-to-WhatsApp). Nunca gasta sin tu aprobación."""
from __future__ import annotations

import html
import json
import logging

import httpx
from sqlalchemy import select

from . import llm, mailer
from .approvals import link
from .config import env, graph_version, public_url, settings
from .content import CAL_SYSTEM, media_path, render_card
from .db import Approval, session, utcnow

log = logging.getLogger(__name__)


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{graph_version()}/{path}"


def _call(method: str, path: str, **kw) -> dict:
    params = {"access_token": env("META_ADS_TOKEN") or env("META_PAGE_TOKEN"), **kw.pop("params", {})}
    r = httpx.request(method, _url(path), params=params, timeout=60, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Marketing API {path}: {r.text[:500]}")
    return r.json()


def propose(budget_hint_mxn: int | None = None) -> int:
    cities = settings()["prospecting"]["cities"]
    prompt = f"""Propón una campaña de Meta Ads (Facebook + Instagram) con objetivo de MENSAJES A WHATSAPP para conseguir demos de Pagoya.
Ciudades: {cities}. Público: dueños y administradores de academias, gimnasios y estudios.
{f'Presupuesto orientativo: ${budget_hint_mxn} MXN al día.' if budget_hint_mxn else 'Propón un presupuesto de prueba prudente (en MXN por día) y duración en días.'}
JSON: {{"nombre": "...", "presupuesto_diario_mxn": int, "dias": int,
"segmentacion": {{"ciudades": ["Monterrey", ...], "radio_km": int, "edad_min": int, "edad_max": int,
"intereses": ["Small business", "Fitness and wellness", ...], "comportamientos": ["Small business owners", ...]}},
"anuncios": [{{"texto_principal": "...", "titulo": "...", "texto_imagen": "máx 10 palabras", "mensaje_bienvenida": "..."}}] (3 variantes),
"razonamiento": "por qué este presupuesto y segmentación, y qué métricas vigilaremos"}}"""
    plan = llm.ask_json(CAL_SYSTEM, prompt)
    with session() as s:
        ap = Approval(kind="ads", ref=plan.get("nombre", "Campaña"), payload=plan)
        s.add(ap)
        s.flush()
        for i, ad in enumerate(plan.get("anuncios", [])):
            ad["imagen"] = render_card(ad.get("texto_imagen", ""), "post", f"ad-{ap.id}-{i}")
        ap.payload = plan
        aid = ap.id
    total = plan["presupuesto_diario_mxn"] * plan["dias"]
    ads_html = "".join(
        f"<li><b>{html.escape(a['titulo'])}</b><br>{html.escape(a['texto_principal'])}<br>"
        f"<a href='{public_url('/media/' + a['imagen'])}'>imagen</a></li>" for a in plan["anuncios"])
    mailer.send_owner(
        f"[Pagoya] Propuesta de anuncios: ${total:,} MXN — necesita tu OK",
        f"""<h2>{html.escape(plan['nombre'])}</h2>
<p><b>Presupuesto:</b> ${plan['presupuesto_diario_mxn']:,} MXN/día × {plan['dias']} días = <b>${total:,} MXN</b></p>
<p><b>Segmentación:</b> <pre>{html.escape(json.dumps(plan['segmentacion'], ensure_ascii=False, indent=1))}</pre></p>
<ol>{ads_html}</ol><p>{html.escape(plan.get('razonamiento', ''))}</p>
<p>No se gasta nada hasta que apruebes:</p>
<p><a href="{link(f'/approve/ads/{aid}', 'ads', aid)}">✅ Aprobar y lanzar</a> &nbsp;|&nbsp;
<a href="{link(f'/reject/ads/{aid}', 'ads', aid)}">❌ Rechazar</a></p>""")
    return aid


def _city_keys(names: list[str], radius_km: int) -> list[dict]:
    out = []
    for n in names:
        res = _call("GET", "search", params={"type": "adgeolocation", "q": n, "location_types": '["city"]',
                                             "country_code": "MX"})
        if res.get("data"):
            out.append({"key": res["data"][0]["key"], "radius": max(radius_km, 17), "distance_unit": "kilometer"})
    return out


def _interest_ids(names: list[str]) -> list[dict]:
    out = []
    for n in names:
        res = _call("GET", "search", params={"type": "adinterest", "q": n})
        if res.get("data"):
            out.append({"id": res["data"][0]["id"], "name": res["data"][0]["name"]})
    return out


def launch(approval_id: int) -> str:
    """Crea la campaña (solo después de tu OK). Se crea en PAUSA y se activa al final."""
    acct = f"act_{env('META_AD_ACCOUNT_ID')}"
    with session() as s:
        ap = s.get(Approval, approval_id)
        plan = ap.payload
    seg = plan["segmentacion"]
    camp = _call("POST", f"{acct}/campaigns", data={
        "name": plan["nombre"], "objective": "OUTCOME_ENGAGEMENT", "status": "PAUSED",
        "special_ad_categories": "[]"})["id"]
    targeting = {"geo_locations": {"cities": _city_keys(seg["ciudades"], seg.get("radio_km", 20))},
                 "age_min": seg.get("edad_min", 25), "age_max": seg.get("edad_max", 60)}
    interests = _interest_ids(seg.get("intereses", []))
    if interests:
        targeting["flexible_spec"] = [{"interests": interests}]
    adset = _call("POST", f"{acct}/adsets", data={
        "name": plan["nombre"] + " - conjunto", "campaign_id": camp, "status": "PAUSED",
        "daily_budget": str(int(plan["presupuesto_diario_mxn"]) * 100), "billing_event": "IMPRESSIONS",
        "optimization_goal": "CONVERSATIONS", "destination_type": "WHATSAPP",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "promoted_object": json.dumps({"page_id": env("META_PAGE_ID")}),
        "targeting": json.dumps(targeting),
        "end_time": str(int(utcnow().timestamp()) + int(plan["dias"]) * 86400)})["id"]
    ad_ids = []
    for i, ad in enumerate(plan["anuncios"]):
        with open(media_path(ad["imagen"]), "rb") as f:
            img = _call("POST", f"{acct}/adimages", files={"filename": (f"ad{i}.jpg", f, "image/jpeg")})
        image_hash = next(iter(img["images"].values()))["hash"]
        creative = _call("POST", f"{acct}/adcreatives", data={
            "name": f"{plan['nombre']} #{i + 1}",
            "object_story_spec": json.dumps({"page_id": env("META_PAGE_ID"), "link_data": {
                "message": ad["texto_principal"], "name": ad["titulo"], "image_hash": image_hash,
                "link": "https://api.whatsapp.com/send",
                "call_to_action": {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}}}}),
        })["id"]
        ad_ids.append(_call("POST", f"{acct}/ads", data={
            "name": f"{plan['nombre']} #{i + 1}", "adset_id": adset, "status": "PAUSED",
            "creative": json.dumps({"creative_id": creative})})["id"])
    for obj in [*ad_ids, adset, camp]:
        _call("POST", obj, data={"status": "ACTIVE"})
    with session() as s:
        ap = s.get(Approval, approval_id)
        ap.payload = {**ap.payload, "campaign_id": camp, "adset_id": adset, "ad_ids": ad_ids}
    return camp


def active_campaign_exists() -> bool:
    with session() as s:
        return bool(s.scalar(select(Approval.id).where(Approval.kind == "ads", Approval.status == "approved")))
