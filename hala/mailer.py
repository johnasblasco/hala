"""Send outreach email from your own mailbox (Gmail by default) over SMTP.

Deliberately simple and slow: one email per click, a daily cap, plain text,
no tracking pixels. Cold email that looks hand-sent lands in inboxes;
bulk blasts land in spam and get the sender's account flagged.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

GMAIL_HOST = "smtp.gmail.com"
DEFAULT_DAILY_LIMIT = 25


class MailError(RuntimeError):
    """Sending failed; the message says what to do (never contains the password)."""


def mail_config(settings: dict) -> dict | None:
    user = (settings.get("smtp_user") or "").strip()
    password = (settings.get("smtp_password") or "").replace(" ", "")
    if not user or not password:
        return None
    host = (settings.get("smtp_host") or "").strip() or GMAIL_HOST
    try:
        port = int(settings.get("smtp_port") or 465)
    except ValueError:
        port = 465
    try:
        limit = max(1, int(settings.get("daily_send_limit") or DEFAULT_DAILY_LIMIT))
    except ValueError:
        limit = DEFAULT_DAILY_LIMIT
    return {"user": user, "password": password, "host": host, "port": port, "limit": limit}


def looks_like_gmail_app_password(value: str) -> bool:
    """Google App Passwords are 16 letters (shown in groups of 4)."""
    return bool(re.fullmatch(r"[a-zA-Z]{16}", value.replace(" ", "")))


def send_email(cfg: dict, to: str, subject: str, body: str, sender_name: str = "",
               _smtp=None) -> str:
    """Send one plain-text email. Returns the Message-ID."""
    to = (to or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
        raise MailError(f"'{to}' doesn't look like an email address.")
    if not subject.strip() or not body.strip():
        raise MailError("The email needs a subject and a message.")
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, cfg["user"])) if sender_name else cfg["user"]
    msg["To"] = to
    msg["Subject"] = subject.strip()
    msg["Reply-To"] = cfg["user"]
    msg["Message-ID"] = make_msgid(domain=cfg["user"].split("@")[-1])
    msg.set_content(body)

    smtp_cls = _smtp or (smtplib.SMTP_SSL if cfg["port"] == 465 else smtplib.SMTP)
    try:
        if cfg["port"] == 465:
            server = smtp_cls(cfg["host"], cfg["port"], timeout=20,
                              context=ssl.create_default_context())
        else:
            server = smtp_cls(cfg["host"], cfg["port"], timeout=20)
        with server:
            if cfg["port"] != 465:
                server.starttls(context=ssl.create_default_context())
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        hint = (" Gmail needs an App Password (Google Account → Security → 2-Step Verification → "
                "App passwords), not your normal password.") if cfg["host"] == GMAIL_HOST else ""
        raise MailError(f"The mail server rejected the login.{hint}") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError(f"The mail server refused the address {to}.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Couldn't send the email: {e}") from e
    return msg["Message-ID"]
