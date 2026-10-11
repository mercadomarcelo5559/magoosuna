"""Programa de referidos + Stripe.

- Cada cliente tiene un link único /r/<CODIGO> (lleva a WhatsApp con el código en el mensaje).
- Cuando el referido se vuelve cliente (webhook de Stripe o lo marcas en el panel):
  * el nuevo recibe 50% de descuento en su primer mes (cupón de Stripe 'once' en su suscripción)
  * quien refirió recibe 1 mes gratis (crédito en su saldo de Stripe = su mensualidad)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx
from sqlalchemy import select

from . import notify
from .config import env, settings
from .db import Prospect, find_prospect, session
from .outreach import mark_client
from .phones import normalize_mx

log = logging.getLogger(__name__)
API = "https://api.stripe.com/v1"


def _stripe(method: str, path: str, data: dict | None = None) -> dict:
    key = env("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("Falta STRIPE_SECRET_KEY")
    r = httpx.request(method, API + path, data=data, auth=(key, ""), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe {path}: {r.text[:300]}")
    return r.json()


def _coupon_50() -> str:
    pct = settings()["referrals"]["referee_discount_percent"]
    cid = f"referido-{pct}"
    try:
        _stripe("GET", f"/coupons/{cid}")
    except RuntimeError:
        _stripe("POST", "/coupons", {"id": cid, "percent_off": pct, "duration": "once",
                                     "name": f"Referido Pagoya {pct}% primer mes"})
    return cid


def verify_stripe(payload: bytes, sig_header: str) -> bool:
    secret = env("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return False
    parts = dict(p.split("=", 1) for p in (sig_header or "").split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig or abs(time.time() - int(ts)) > 600:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _monthly_amount_cents(customer_id: str) -> int:
    subs = _stripe("GET", f"/subscriptions?customer={customer_id}&status=active&limit=1").get("data", [])
    if not subs:
        return 0
    item = subs[0]["items"]["data"][0]
    price = item["price"]
    amount = price.get("unit_amount") or 0
    interval = price.get("recurring", {}).get("interval", "month")
    count = price.get("recurring", {}).get("interval_count", 1)
    if interval == "year":
        amount = amount // (12 * count)
    return amount * item.get("quantity", 1)


def on_new_client(prospect_id: int, subscription_id: str | None = None) -> dict:
    """Marca cliente y aplica recompensas de referido si corresponde."""
    res = {}
    with session() as s:
        p = s.get(Prospect, prospect_id)
        mark_client(s, p)
        ref = s.get(Prospect, p.referred_by_id) if p.referred_by_id else None
        if not ref or "recompensa_referido" in (p.notes or ""):
            return res
        p.notes = (p.notes or "") + "\nrecompensa_referido"
        try:
            if subscription_id:
                _stripe("POST", f"/subscriptions/{subscription_id}", {"coupon": _coupon_50()})
                res["referee_discount"] = True
            if ref.stripe_customer_id:
                cents = _monthly_amount_cents(ref.stripe_customer_id) * settings()["referrals"]["referrer_reward_months"]
                if cents:
                    _stripe("POST", f"/customers/{ref.stripe_customer_id}/balance_transactions",
                            {"amount": -cents, "currency": "mxn",
                             "description": f"Mes gratis por referir a {p.name}"})
                    res["referrer_credit_cents"] = cents
        except Exception as e:  # noqa: BLE001
            log.exception("Stripe referido falló")
            notify.owner_alert("Aplica manualmente la recompensa de referido",
                               f"{ref.name} refirió a {p.name}. Error de Stripe: {e}")
            return res
        notify.owner_alert("¡Referido convertido!",
                           f"{ref.name} refirió a {p.name}. Recompensas aplicadas en Stripe: {res}")
    return res


def handle_stripe_event(event: dict) -> None:
    t = event.get("type")
    obj = event.get("data", {}).get("object", {})
    if t not in ("customer.subscription.created", "checkout.session.completed"):
        return
    customer_id = obj.get("customer")
    sub_id = obj.get("id") if t == "customer.subscription.created" else obj.get("subscription")
    cust = _stripe("GET", f"/customers/{customer_id}") if customer_id else {}
    phone = normalize_mx(cust.get("phone") or (cust.get("metadata") or {}).get("whatsapp"))
    email = (cust.get("email") or "").lower() or None
    code = ((cust.get("metadata") or {}).get("referral_code") or
            (obj.get("metadata") or {}).get("referral_code") or "").upper()
    with session() as s:
        p = find_prospect(s, phone=phone, email=email)
        if not p:
            p = Prospect(name=cust.get("name") or "", phone=phone, email=email, source="WhatsApp directo")
            s.add(p)
            s.flush()
        p.stripe_customer_id = customer_id
        if code and not p.referred_by_id:
            ref = s.scalar(select(Prospect).where(Prospect.referral_code == code))
            if ref and ref.id != p.id:
                p.referred_by_id = ref.id
        pid = p.id
    on_new_client(pid, sub_id)
