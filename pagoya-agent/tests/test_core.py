import datetime as dt
import os
from types import SimpleNamespace

import pytest

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["TEST_MODE"] = "true"
os.environ["OWNER_WHATSAPP"] = "+52 81 1234 5678"
os.environ["SECRET_KEY"] = "test"
os.environ["GMAIL_USER"] = ""
os.environ["ANTHROPIC_API_KEY"] = "sk-test"

from pagoya import bot, db, outreach, whatsapp  # noqa: E402
from pagoya.phones import normalize_mx  # noqa: E402
from pagoya.pricing import quote  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    db.reset_engine()
    sent = []

    def fake_send(to, template, params=None, button=None):
        sent.append((to, template, params))
        return f"wamid.{len(sent)}"
    monkeypatch.setattr(whatsapp, "send_template", fake_send)
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text: sent.append((to, "text", text)) or "wamid.t")
    monkeypatch.setattr(whatsapp, "mark_read", lambda mid: None)
    yield sent
    db.reset_engine()


def test_normalize():
    assert normalize_mx("(81) 1234-5678") == "+528112345678"
    assert normalize_mx("+52 1 81 1234 5678") == "+528112345678"
    assert normalize_mx("5218112345678") == "+528112345678"
    assert normalize_mx("044 81 1234 5678") == "+528112345678"
    assert normalize_mx("12345") is None


def test_pricing():
    assert quote(30)["monthly"] == 399
    assert quote(41)["plan"] == "Estándar"
    assert quote(200)["monthly"] == 1199
    assert quote(401)["monthly"] == 2499 and "desde" in quote(401)["text"]
    assert quote(80)["annual"] == 7990


def _mk(s, n, **kw):
    for i in range(n):
        s.add(db.Prospect(name=f"Academia {i}", category="natación", phone=f"+52811000{i:04d}",
                          phone_kind="mobile", reviews=i, **kw))


def test_invitations_count_only_delivered(fresh_db, monkeypatch):
    from pagoya.timeutil import local_naive
    start, end = local_naive() - dt.timedelta(hours=1), local_naive() + dt.timedelta(hours=1)
    monkeypatch.setattr(outreach, "current_slot", lambda now=None: ("morning", start, end))
    now = None
    with db.session() as s:
        _mk(s, 200)
    r1 = outreach.run_invitations(now)
    assert r1["sent_now"] == 15
    # mientras estén pendientes no se manda más que la cuota
    with db.session() as s:
        for m in s.scalars(db.select(db.Message)):
            m.status = "failed"  # fallidos no cuentan como entregados
    r2 = outreach.run_invitations(now)
    assert r2["sent_now"] == 15 and r2["delivered"] == 0
    with db.session() as s:
        for m in s.scalars(db.select(db.Message).where(db.Message.status == "sent")):
            outreach.apply_status(s, {"id": m.external_id, "status": "delivered"})
    with db.session() as s:
        c = outreach.slot_counts(s, start, end)
    assert c["delivered"] == 15
    # 15 entregados + 0 pendientes -> faltan 45; manda otra ronda de 15
    assert outreach.run_invitations(now)["sent_now"] == 15


def test_quality_yellow_halves_red_pauses(monkeypatch):
    monkeypatch.setattr("pagoya.notify._safe_send", lambda *a: None)
    with db.session() as s:
        outreach.apply_quality(s, "YELLOW")
        assert outreach.quality_factor(s) == 0.5
        outreach.apply_quality(s, "RED")
        assert outreach.quality_factor(s) == 0
        outreach.apply_quality(s, "GREEN")
        assert outreach.quality_factor(s) == 0  # sigue pausado hasta que lo reanudes


def test_outside_hours():
    assert outreach.run_invitations(dt.datetime(2026, 10, 17, 11, 0))["skipped"]  # sábado
    assert outreach.run_invitations(dt.datetime(2026, 10, 12, 14, 0))["skipped"]


def test_opt_out_and_never_again(monkeypatch):
    monkeypatch.setattr("pagoya.notify._safe_send", lambda *a: None)
    with db.session() as s:
        _mk(s, 1)
    with db.session() as s:
        p = s.scalar(db.select(db.Prospect))
        reply, out = bot.handle_inbound(s, p, "whatsapp", "BAJA")
        assert reply == "" and p.do_not_contact and p.status == db.BAJA
    assert outreach.run_invitations(dt.datetime(2026, 10, 12, 10, 30))["sent_now"] == 0
    assert bot.is_opt_out("ya no me escriban por favor")
    assert not bot.is_opt_out("¿cuánto cuesta?")


def test_price_requires_students(monkeypatch):
    monkeypatch.setattr("pagoya.notify._safe_send", lambda *a: None)
    with db.session() as s:
        _mk(s, 1)
        s.flush()
        p = s.scalar(db.select(db.Prospect))
        o = bot.Outcome()
        assert bot.run_tool(s, p, "cotizar", {}, o, "whatsapp").startswith("ERROR")
        bot.run_tool(s, p, "registrar_alumnos", {"alumnos": 120}, o, "whatsapp")
        assert "Pro" in bot.run_tool(s, p, "cotizar", {}, o, "whatsapp")
        assert p.status == db.CALIFICADO


def test_book_demo(monkeypatch):
    monkeypatch.setattr("pagoya.notify._safe_send", lambda *a: None)
    from pagoya import scheduling
    with db.session() as s:
        _mk(s, 1)
        s.flush()
        p = s.scalar(db.select(db.Prospect))
        slots = scheduling.available_slots(s)
        assert slots and all(10 <= t.hour < 18 and t.weekday() <= 5 for t in slots)
        o = bot.Outcome()
        r = bot.run_tool(s, p, "agendar_demo", {"fecha_hora": slots[0].strftime("%Y-%m-%d %H:%M"),
                                                "nombre_contacto": "Ana"}, o, "whatsapp")
        assert "Demo agendada" in r and p.status == db.DEMO
        r2 = bot.run_tool(s, p, "agendar_demo", {"fecha_hora": slots[0].strftime("%Y-%m-%d %H:%M"),
                                                 "nombre_contacto": "Ana"}, o, "whatsapp")
        assert "ocupado" in r2
        # domingo no
        sunday = slots[0] + dt.timedelta(days=(6 - slots[0].weekday()))
        assert not scheduling.is_valid_slot(s, sunday.replace(hour=11, minute=0))[0]


def test_bot_loop_with_fake_llm(monkeypatch, fresh_db):
    monkeypatch.setattr("pagoya.notify._safe_send", lambda *a: None)
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t1", name="registrar_alumnos", input={"alumnos": 50})])
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="¡Perfecto!")])
    monkeypatch.setattr("pagoya.llm.create", fake_create)
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": "5218112345678", "profile": {"name": "Ana"}}],
        "messages": [{"id": "wamid.in1", "from": "5218112345678", "type": "text",
                      "text": {"body": "Tenemos 50 alumnos"}}]}}]}]}
    outreach.process_webhook(payload)
    outreach.process_webhook(payload)  # duplicado ignorado
    with db.session() as s:
        p = s.scalar(db.select(db.Prospect))
        assert p.phone == "+528112345678" and p.students == 50 and p.status == db.CALIFICADO
        assert p.source == "WhatsApp directo"
    assert len(calls) == 2
    assert fresh_db[-1][1] == "text" and fresh_db[-1][2] == "¡Perfecto!"


def test_lead_endpoint_and_hot_contact(fresh_db):
    from fastapi.testclient import TestClient
    from pagoya.server import app
    c = TestClient(app)
    r = c.post("/api/lead", json={"students": 100, "fee": 900, "late": 20, "name": "Luis",
                                  "academy": "Karate Do", "whatsapp": "81 2222 3333", "consent": True})
    assert r.status_code == 200 and r.json()["calc"]["perdida_anual"] > 0
    with db.session() as s:
        p = s.scalar(db.select(db.Prospect))
        assert p.hot and p.source == "Calculadora" and p.invited_at is not None
    assert any(t[1] == "resultado_calculadora" for t in fresh_db)
    assert c.post("/api/lead", json={"students": 1, "fee": 1, "late": 1, "name": "x", "academy": "y",
                                     "whatsapp": "123", "consent": True}).status_code == 422


def test_followup_once(monkeypatch, fresh_db):
    monkeypatch.setattr(outreach, "current_slot", lambda now=None: ("morning", None, None))
    with db.session() as s:
        _mk(s, 3)
        s.flush()
        for p in s.scalars(db.select(db.Prospect)):
            p.status = db.INVITADO
            p.invited_at = db.utcnow() - dt.timedelta(days=4)
    assert outreach.run_followups()["followups"] == 3
    assert outreach.run_followups()["followups"] == 0


def test_report_builds(monkeypatch):
    monkeypatch.setattr("pagoya.social.snapshot_metrics", lambda: {"ig_followers": 10})
    from pagoya.reports import build_daily
    subject, body = build_daily()
    assert "Resumen" in subject and "Calidad del número" in body


def test_approval_links():
    from pagoya import approvals
    url = approvals.link("/approve/ads/3", "ads", 3)
    t = url.split("t=")[1]
    assert approvals.check(t, "/approve/ads/3", "ads", 3)
    assert not approvals.check(t, "/approve/ads/4", "ads", 4)


def test_scheduler_jobs_build():
    from pagoya.scheduler import jobs
    names = [n for n, _, _ in jobs()]
    assert "invitaciones" in names and "resumen_diario" in names


def test_site_build(monkeypatch, tmp_path):
    from pagoya import seo
    monkeypatch.setattr(seo, "OUT", tmp_path / "out")
    monkeypatch.setattr(seo, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(seo.llm, "ask_json", lambda *a, **k: {
        "title": "T", "meta": "M", "h1": "H1", "intro": "a\nb", "problemas": ["p"], "como_ayuda": ["c"],
        "faq": [{"q": "¿Precio?", "a": "Desde $399"}]})
    res = seo.build_site(max_new=3)
    assert res["pages"] == 3
    assert (tmp_path / "out" / "calculadora" / "index.html").exists()
    assert (tmp_path / "out" / "sitemap-pagoya.xml").exists()


def test_calc():
    from pagoya.seo import calc_loss
    c = calc_loss(100, 1000, 20)
    assert c["atrasado_anual"] == 240000 and c["no_recuperado"] == 60000
