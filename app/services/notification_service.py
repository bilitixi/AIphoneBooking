import logging

from twilio.rest import Client as TwilioClient

from app.core.config import get_settings
from app.db.models import Customer, Reservation

logger = logging.getLogger(__name__)


def _twilio_client() -> TwilioClient:
    settings = get_settings()
    return TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)


def _confirmation_text(reservation: Reservation) -> str:
    when = reservation.starts_at.strftime("%a %d %b, %I:%M %p")
    return (
        f"ABC Restaurant: your table for {reservation.party_size} on {when} "
        f"is confirmed. Reply to this number if you need to change or cancel."
    )


async def send_reservation_confirmation(customer: Customer, reservation: Reservation) -> None:
    settings = get_settings()
    channels = {c.strip() for c in settings.notification_channels.split(",") if c.strip()}

    if "sms" in channels:
        await _send_sms(customer.phone_number, _confirmation_text(reservation))
    if "email" in channels and customer.email:
        await _send_email(customer.email, _confirmation_text(reservation))


async def _send_sms(to_number: str, body: str) -> None:
    settings = get_settings()
    try:
        _twilio_client().messages.create(to=to_number, from_=settings.twilio_sms_from, body=body)
    except Exception:
        logger.exception("Failed to send SMS confirmation to %s", to_number)


async def _send_email(to_address: str, body: str) -> None:
    # Wire up a transactional email provider (e.g. SES, Postmark, SendGrid)
    # here once §7.3 (SMS vs email vs both) is decided.
    logger.info("Would send email confirmation to %s: %s", to_address, body)
