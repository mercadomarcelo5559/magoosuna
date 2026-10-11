"""Correo: Gmail (reportes/avisos a ti) y buzón secundario (correo en frío)."""
from __future__ import annotations

import email
import imaplib
import logging
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from .config import env, test_mode

log = logging.getLogger(__name__)
OUTBOX: list[EmailMessage] = []  # cuando no hay credenciales (pruebas), los correos quedan aquí


def _send(msg: EmailMessage, host: str, port: int, user: str, password: str) -> None:
    if not (user and password):
        log.warning("Correo no configurado; se guarda en OUTBOX: %s", msg["Subject"])
        OUTBOX.append(msg)
        return
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


def send_owner(subject: str, html: str, text: str | None = None, reply_to: str | None = None) -> None:
    """Correo para ti (reporte diario, avisos, aprobaciones)."""
    user = env("GMAIL_USER")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Pagoya Agent", user or "agent@pagoya.com.mx"))
    msg["To"] = env("OWNER_EMAIL")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text or "Abre este correo en formato HTML.")
    msg.add_alternative(html, subtype="html")
    _send(msg, "smtp.gmail.com", 587, user, env("GMAIL_APP_PASSWORD"))


def send_cold(to: str, subject: str, text: str, html: str, unsubscribe_url: str,
              in_reply_to: str | None = None) -> str:
    """Correo en frío desde el dominio secundario, con baja en un clic (RFC 8058)."""
    user = env("COLD_EMAIL_USER")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((env("COLD_EMAIL_FROM_NAME", "Pagoya"), user))
    msg["To"] = env("OWNER_EMAIL") if test_mode() else to
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>, <mailto:{user}?subject=BAJA>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    mid = make_msgid(domain=(user.split("@")[-1] if "@" in user else "pagoyamx.com"))
    msg["Message-ID"] = mid
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    _send(msg, env("COLD_SMTP_HOST", "smtp.gmail.com"), int(env("COLD_SMTP_PORT", "587")),
          user, env("COLD_EMAIL_PASSWORD"))
    return mid


def _decode(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def fetch_unseen(host: str, user: str, password: str, since: str | None = None,
                 subject_contains: str | None = None) -> list[dict]:
    """Lee correos no leídos (IMAP). since en formato '11-Oct-2026'."""
    if not (user and password):
        return []
    out = []
    with imaplib.IMAP4_SSL(host) as im:
        im.login(user, password)
        im.select("INBOX")
        crit = ["UNSEEN"]
        if since:
            crit += ["SINCE", since]
        if subject_contains:
            crit += ["SUBJECT", f'"{subject_contains}"']
        typ, data = im.search(None, *crit)
        for num in (data[0].split() if data and data[0] else []):
            typ, msg_data = im.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            out.append({
                "from": parseaddr(msg.get("From"))[1].lower(),
                "subject": _decode(msg.get("Subject")),
                "in_reply_to": msg.get("In-Reply-To", ""),
                "body": _body(msg),
            })
    return out


def strip_quoted(body: str) -> str:
    lines = []
    for line in body.splitlines():
        if line.startswith(">") or (line.startswith("El ") and "escribió:" in line) or \
                (line.startswith("On ") and "wrote:" in line):
            break
        lines.append(line)
    return "\n".join(lines).strip()
