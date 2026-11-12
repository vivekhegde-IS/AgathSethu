"""
AGHAT SETHU — Welcome email on a user's first login.

The login route claims the user's welcome (users.welcome_email_sent_at, set
atomically so two parallel logins cannot both send) and schedules
send_welcome_email() as a background task, so the login response never waits
for SMTP. A failed send releases the claim, and the next login tries again.

Citizens and authority officers (authority/admin) get different emails.
Sending is off while SMTP_USER / SMTP_PASSWORD are empty.
"""

import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import User

logger = logging.getLogger(__name__)

AUTHORITY_ROLES = {"authority", "admin"}


def email_enabled() -> bool:
    return bool(settings.SMTP_USER and settings.SMTP_PASSWORD)


def claim_welcome(db: Session, user_id: uuid.UUID) -> bool:
    """Mark the welcome as sent; True only for the one call that set it."""
    result = db.execute(
        update(User)
        .where(User.id == user_id, User.welcome_email_sent_at.is_(None))
        .values(welcome_email_sent_at=datetime.now(timezone.utc))
    )
    db.commit()
    return result.rowcount == 1


def _release_welcome(user_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        db.execute(update(User).where(User.id == user_id).values(welcome_email_sent_at=None))
        db.commit()
    finally:
        db.close()


_CITIZEN = {
    "subject": "Welcome to AGHAT SETHU",
    "heading": "Welcome to AGHAT SETHU",
    "intro": "Your citizen account is ready. AGHAT SETHU keeps you informed about your vehicles "
             "and helps make our roads safer.",
    "items": [
        "View the fines and challans issued to your vehicles, with photo and video evidence",
        "Pay fines online and download your receipts",
        "Get notified if a vehicle of yours is involved in a road incident",
        "Keep your profile and vehicle details up to date",
    ],
    "button": "Go to my dashboard",
    "path": "/citizen/dashboard",
    "closing": "Drive safe, and thank you for being part of a safer road network.",
}

_AUTHORITY = {
    "subject": "Welcome to AGHAT SETHU – Authority Access Activated",
    "heading": "Authority access activated",
    "intro": "Your authority account on AGHAT SETHU is now active. You have access to the "
             "traffic safety and incident-response tools for your jurisdiction.",
    "items": [
        "Live junction camera feeds and junction tracking",
        "Incident dashboard with crash alerts, evidence and resolution",
        "Level 1 routine violation detection from traffic videos (helmet, number plate)",
        "Fine management, revenue overview and evidence records",
    ],
    "button": "Open the authority dashboard",
    "path": "/authority/dashboard",
    "closing": "For security, never share your login, and sign out on shared computers. "
               "If you did not expect this account, contact your administrator.",
}


def build_welcome_message(full_name: str, email: str, role: str) -> EmailMessage:
    content = _AUTHORITY if role in AUTHORITY_ROLES else _CITIZEN
    link = settings.SITE_URL.rstrip("/") + content["path"]
    name = full_name.strip() or "there"

    text = "\n".join(
        [f"Hello {name},", "", content["intro"], "", "What you can do:"]
        + [f"  - {item}" for item in content["items"]]
        + ["", f"{content['button']}: {link}", "", content["closing"], "", "— Team AGHAT SETHU"]
    )

    items_html = "".join(
        f'<li style="margin:0 0 8px">{escape(item)}</li>' for item in content["items"]
    )
    html = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden">
  <tr><td style="background:#0f172a;padding:20px 28px;color:#ffffff;font-size:20px;font-weight:bold;letter-spacing:1px">AGHAT SETHU</td></tr>
  <tr><td style="padding:28px">
    <h1 style="margin:0 0 16px;font-size:22px">{escape(content["heading"])}</h1>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.5">Hello {escape(name)},</p>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.5">{escape(content["intro"])}</p>
    <p style="margin:0 0 8px;font-size:15px;font-weight:bold">What you can do:</p>
    <ul style="margin:0 0 24px;padding-left:20px;font-size:15px;line-height:1.5">{items_html}</ul>
    <a href="{escape(link)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;font-size:15px;font-weight:bold">{escape(content["button"])}</a>
    <p style="margin:24px 0 0;font-size:14px;line-height:1.5;color:#475569">{escape(content["closing"])}</p>
    <p style="margin:16px 0 0;font-size:14px;color:#475569">— Team AGHAT SETHU</p>
  </td></tr>
  <tr><td style="background:#f8fafc;padding:14px 28px;font-size:12px;color:#64748b">You received this email because an AGHAT SETHU account was created with {escape(email)}.</td></tr>
</table>
</td></tr>
</table>
</body></html>
"""

    message = EmailMessage()
    message["Subject"] = content["subject"]
    message["From"] = formataddr((settings.MAIL_FROM_NAME, settings.SMTP_USER))
    message["To"] = email
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_welcome_email(user_id: uuid.UUID, full_name: str, email: str, role: str) -> None:
    """Background task: send the welcome; on failure release the claim."""
    try:
        message = build_welcome_message(full_name, email, role)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        logger.info("[WELCOME] sent %s welcome email to %s", role, email)
    except Exception as error:
        logger.warning("[WELCOME] could not send to %s: %s", email, error)
        _release_welcome(user_id)
