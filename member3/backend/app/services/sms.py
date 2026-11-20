"""
AGHAT SETHU — Text messages (SMS)

``SmsProvider`` sends one message; ``send_sms`` stores every message in
``sms_messages`` (that is what the owner's phone-style panel shows) and hands
it to the active provider.

  ConsoleSmsProvider  default: logs the message, sends nothing
  TwilioSmsProvider   only when TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
                      TWILIO_FROM_NUMBER are all set

Placeholder numbers (the seeded demo owners: +9100000...) are NEVER sent to a
real provider, whatever the configuration.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings
from app.models.live import SmsMessage

log = logging.getLogger("aghat.sms")

PLACEHOLDER_PREFIX = "+9100000"


def is_placeholder_number(number: str | None) -> bool:
    digits = "+" + re.sub(r"\D", "", number or "")
    return not number or digits.startswith(PLACEHOLDER_PREFIX)


class SmsProvider:
    name = "base"

    def send(self, to_number: str, body: str) -> tuple[str, str | None]:
        """Returns (status, provider_ref)."""
        raise NotImplementedError


class ConsoleSmsProvider(SmsProvider):
    name = "console"

    def send(self, to_number: str, body: str) -> tuple[str, str | None]:
        print(f"[SMS console] to={to_number or '-'}: {body}", flush=True)
        return "stored", None


class TwilioSmsProvider(SmsProvider):
    name = "twilio"

    def __init__(self, sid: str, token: str, from_number: str) -> None:
        self.sid, self.token, self.from_number = sid, token, from_number

    def send(self, to_number: str, body: str) -> tuple[str, str | None]:
        if is_placeholder_number(to_number):
            print(f"[SMS twilio] placeholder number {to_number!r}: not sent", flush=True)
            return "skipped_placeholder", None
        try:
            response = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                data={"To": to_number, "From": self.from_number, "Body": body},
                auth=(self.sid, self.token), timeout=10.0)
            response.raise_for_status()
            return "sent", str(response.json().get("sid") or "")[:64] or None
        except Exception as error:     # never let SMS break crash handling
            log.warning("Twilio send failed: %s", error)
            return "failed", None


def get_provider() -> SmsProvider:
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER:
        return TwilioSmsProvider(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN,
                                 settings.TWILIO_FROM_NUMBER)
    return ConsoleSmsProvider()


def send_sms(db, user, body: str, notification_id=None, provider: SmsProvider | None = None) -> SmsMessage:
    """Store the message, then send it. Caller commits."""
    provider = provider or get_provider()
    status, ref = provider.send(user.phone or "", body)
    message = SmsMessage(user_id=user.id, notification_id=notification_id, to_number=user.phone,
                         body=body, provider=provider.name, status=status, provider_ref=ref)
    db.add(message)
    db.flush()
    return message


def sms_view(message: SmsMessage) -> dict:
    return {"id": message.id, "body": message.body, "to_number": message.to_number,
            "provider": message.provider, "status": message.status,
            "read": message.read_at is not None,
            "created_at": message.created_at.isoformat() if message.created_at else None}
