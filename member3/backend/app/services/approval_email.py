"""
AGHAT SETHU — Email to an officer when an admin approves or rejects their
sign-up. Sent as a background task (the admin's click never waits for SMTP),
with the same SMTP settings as the welcome email. Off while SMTP_USER /
SMTP_PASSWORD are empty; never sent to reserved test domains.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from app.core.config import settings
from app.services.welcome_email import email_enabled

logger = logging.getLogger(__name__)

# example.com and friends never receive real mail (demo / test accounts)
_RESERVED = ("example.com", "example.org", "example.net")
_RESERVED_SUFFIXES = (".local", ".test", ".invalid", ".example")


def _deliverable(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain not in _RESERVED and not domain.endswith(_RESERVED_SUFFIXES)


def build_decision_message(full_name: str, email: str, approved: bool) -> EmailMessage:
    name = full_name.strip() or "there"
    link = settings.SITE_URL.rstrip("/") + "/authority/login"
    if approved:
        subject = "Your AGHAT SETHU officer account is approved"
        heading = "You can now sign in"
        body = ("An administrator has approved your traffic-authority account. You can now sign in to "
                "the AGHAT SETHU control room on the website or in the mobile app.")
        button = "Sign in"
    else:
        subject = "Your AGHAT SETHU officer sign-up"
        heading = "Sign-up not approved"
        body = ("Your request for a traffic-authority account was not approved. If you think this is a "
                "mistake, please contact your AGHAT SETHU administrator.")
        button = None
    text = "\n".join([f"Hello {name},", "", body, ""] + ([f"{button}: {link}", ""] if button else [])
                     + ["— Team AGHAT SETHU"])
    action = (f'<a href="{escape(link)}" style="display:inline-block;background:#2563eb;color:#ffffff;'
              f'text-decoration:none;padding:12px 22px;border-radius:8px;font-size:15px;font-weight:bold">'
              f'{escape(button)}</a>') if button else ""
    html = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden">
  <tr><td style="background:#0f172a;padding:20px 28px;color:#ffffff;font-size:20px;font-weight:bold;letter-spacing:1px">AGHAT SETHU</td></tr>
  <tr><td style="padding:28px">
    <h1 style="margin:0 0 16px;font-size:22px">{escape(heading)}</h1>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.5">Hello {escape(name)},</p>
    <p style="margin:0 0 24px;font-size:15px;line-height:1.5">{escape(body)}</p>
    {action}
    <p style="margin:24px 0 0;font-size:14px;color:#475569">— Team AGHAT SETHU</p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>
"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.MAIL_FROM_NAME, settings.SMTP_USER))
    message["To"] = email
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_decision_email(full_name: str, email: str, approved: bool) -> None:
    """Background task. Failures are logged, never raised."""
    if not email_enabled() or not _deliverable(email):
        logger.info("[APPROVAL] email not sent to %s (mail off or reserved domain)", email)
        return
    try:
        message = build_decision_message(full_name, email, approved)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        logger.info("[APPROVAL] sent %s email to %s", "approval" if approved else "rejection", email)
    except Exception as error:
        logger.warning("[APPROVAL] could not send to %s: %s", email, error)
