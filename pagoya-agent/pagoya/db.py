"""Base de datos / CRM. SQLite en local, Postgres en producción (DATABASE_URL)."""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import env

# Estados del embudo
NUEVO, INVITADO, RESPONDIO, CALIFICADO, DEMO, CLIENTE, PERDIDO, BAJA = (
    "nuevo", "invitado", "respondió", "calificado", "demo agendada", "cliente", "perdido", "baja",
)
STATUSES = [NUEVO, INVITADO, RESPONDIO, CALIFICADO, DEMO, CLIENTE, PERDIDO, BAJA]
_RANK = {s: i for i, s in enumerate(STATUSES)}

# Canales de origen
SOURCES = ["Google Places", "Instagram", "Facebook", "Calculadora", "SEO", "Referido",
           "Correo en frío", "Google Business", "Anuncios", "Alianza", "Directorio", "WhatsApp directo"]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Prospect(Base):
    __tablename__ = "prospects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    raw_phone: Mapped[str] = mapped_column(String(40), default="")
    phone_kind: Mapped[str] = mapped_column(String(12), default="unknown")  # mobile/fixed/unknown
    email: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    website: Mapped[str] = mapped_column(String(300), default="")
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    instagram_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    facebook_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="Google Places")
    status: Mapped[str] = mapped_column(String(30), default=NUEVO, index=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    hot: Mapped[bool] = mapped_column(Boolean, default=False)
    students: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    bot_paused: Mapped[bool] = mapped_column(Boolean, default=False)  # pasado a humano
    referral_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    invited_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    followup_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_inbound_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    client_since: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    referral_invite_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    review_request_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cold_email_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cold_followup_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(back_populates="prospect", order_by="Message.id")

    def advance(self, status: str) -> None:
        """Sube de estado sin retroceder (salvo perdido/baja, que son terminales)."""
        if self.status == BAJA:
            return
        if status in (BAJA, PERDIDO) or _RANK.get(status, 0) > _RANK.get(self.status, 0):
            self.status = status
        if status == BAJA:
            self.do_not_contact = True


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), index=True, nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")  # whatsapp/instagram/facebook/email
    direction: Mapped[str] = mapped_column(String(4))  # in / out
    kind: Mapped[str] = mapped_column(String(30), default="text")  # text/invitation/followup/...
    template: Mapped[str] = mapped_column(String(80), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="")  # sent/delivered/read/failed
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    prospect: Mapped[Prospect | None] = relationship(back_populates="messages")


class Demo(Base):
    __tablename__ = "demos"
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"))
    start_local: Mapped[dt.datetime] = mapped_column(DateTime)  # hora de Monterrey (naive)
    duration: Mapped[int] = mapped_column(Integer, default=30)
    zoom_url: Mapped[str] = mapped_column(String(400), default="")
    zoom_id: Mapped[str] = mapped_column(String(40), default="")
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    academy: Mapped[str] = mapped_column(String(200), default="")
    students: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    source: Mapped[str] = mapped_column(String(40), default="")
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    prospect: Mapped[Prospect] = relationship()


class SharedContact(Base):
    """Contactos que un prospecto comparte en la conversación (p. ej. 'habla con mi socio')."""
    __tablename__ = "shared_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    academy: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class KV(Base):
    """Estado global: quality rating, pausa, snapshots de métricas, etc."""
    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ContentItem(Base):
    """Calendario de redes sociales."""
    __tablename__ = "content_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    week: Mapped[str] = mapped_column(String(10), index=True)  # 2026-W42
    kind: Mapped[str] = mapped_column(String(10))  # post / reel / story
    pillar: Mapped[str] = mapped_column(String(40), default="")  # app/tip/caso/promo
    publish_at_local: Mapped[dt.datetime] = mapped_column(DateTime)
    title: Mapped[str] = mapped_column(String(200), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    script: Mapped[str] = mapped_column(Text, default="")  # guion de reel
    image_text: Mapped[str] = mapped_column(Text, default="")
    media_file: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/approved/published/failed/hold
    result: Mapped[str] = mapped_column(Text, default="")


class Approval(Base):
    """Cosas que esperan tu OK: calendario, anuncios, propuesta de alianzas, respuestas a reseñas."""
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # calendar/ads/partners/review_reply
    ref: Mapped[str] = mapped_column(String(80), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected/changes
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Partner(Base):
    __tablename__ = "partners"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(60))
    city: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    place_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="lista")  # lista/contactado/interesado/aliado/no
    contacted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[float] = mapped_column(Float, default=0)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = env("DATABASE_URL", "sqlite:///pagoya.db")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        kw = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                from sqlalchemy.pool import StaticPool
                kw["poolclass"] = StaticPool
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
    return _engine


def reset_engine():
    global _engine, _Session
    _engine = None
    _Session = None


@contextmanager
def session():
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def kv_get(s, key: str, default=None):
    row = s.get(KV, key)
    return row.value if row else default


def kv_set(s, key: str, value) -> None:
    row = s.get(KV, key)
    if row:
        row.value = value
    else:
        s.add(KV(key=key, value=value))


def find_prospect(s, *, phone=None, email=None, instagram_id=None, facebook_id=None):
    for col, val in ((Prospect.phone, phone), (Prospect.email, email),
                     (Prospect.instagram_id, instagram_id), (Prospect.facebook_id, facebook_id)):
        if val:
            p = s.scalar(select(Prospect).where(col == val))
            if p:
                return p
    return None
