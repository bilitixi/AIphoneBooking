"""Tool implementations invoked by the Claude tool-call loop.

Every function here is a thin wrapper around services/ — no direct DB
access — so booking logic (including the concurrency handling in
create_reservation) stays identical whether it's triggered by this AI
agent or the admin portal.
"""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services import customer_service, reservation_service

_DAY_NAME_DESCRIPTION = (
    "The weekday name the caller said (e.g. 'Thursday'), matching the row "
    "starts_at was read from in the calendar. Lets the backend catch a "
    "misread of the calendar (e.g. picking the wrong row) before booking."
)


def _local_weekday(starts_at: datetime) -> str:
    """The authoritative weekday name for starts_at, in restaurant-local
    terms. This is the only source of truth for weekday names — the agent
    must read this from tool results rather than computing it itself."""
    tz = ZoneInfo(get_settings().restaurant_timezone)
    local = starts_at.astimezone(tz) if starts_at.tzinfo else starts_at.replace(tzinfo=tz)
    return local.strftime("%A")


def _weekday_mismatch(starts_at: datetime, day_name: str | None) -> dict | None:
    """Returns an error dict if starts_at doesn't actually fall on day_name,
    else None. starts_at is checked in restaurant-local terms, since that's
    the calendar the agent was given."""
    if not day_name:
        return None
    actual = _local_weekday(starts_at)
    if actual.lower() != day_name.strip().lower():
        return {
            "error": (
                f"{starts_at.date().isoformat()} is a {actual}, not {day_name}. "
                "Re-check the calendar in the system prompt and pass the date "
                "from the row that actually has that weekday name."
            )
        }
    return None

TOOL_DEFINITIONS = [
    {
        "name": "find_customer",
        "description": "Look up an existing customer by phone number.",
        "input_schema": {
            "type": "object",
            "properties": {"phone_number": {"type": "string"}},
            "required": ["phone_number"],
        },
    },
    {
        "name": "check_availability",
        "description": "Check whether the restaurant can seat a party at a given date/time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "starts_at": {"type": "string", "description": "ISO-8601 datetime"},
                "party_size": {"type": "integer"},
                "day_name": {"type": "string", "description": _DAY_NAME_DESCRIPTION},
            },
            "required": ["starts_at", "party_size"],
        },
    },
    {
        "name": "create_reservation",
        "description": (
            "Book a reservation. May fail if the slot filled up since "
            "check_availability was called — in that case, offer the caller "
            "other times instead of retrying blindly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string"},
                "customer_name": {"type": "string", "description": "The caller's name for the booking."},
                "party_size": {"type": "integer"},
                "starts_at": {"type": "string", "description": "ISO-8601 datetime"},
                "day_name": {"type": "string", "description": _DAY_NAME_DESCRIPTION},
                "special_requests": {
                    "type": "string",
                    "description": "Any notes the caller wants to leave (allergies, occasions, seating preferences).",
                },
            },
            "required": ["phone_number", "customer_name", "party_size", "starts_at"],
        },
    },
    {
        "name": "find_reservations",
        "description": (
            "List the caller's upcoming confirmed reservations. Always call "
            "this before modify_reservation or cancel_reservation to get the "
            "exact reservation_id — never guess or reuse IDs from elsewhere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"phone_number": {"type": "string"}},
            "required": ["phone_number"],
        },
    },
    {
        "name": "modify_reservation",
        "description": (
            "Change an existing reservation belonging to the calling phone "
            "number. Use a reservation_id returned by find_reservations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reservation_id": {"type": "string"},
                "phone_number": {"type": "string"},
                "starts_at": {"type": "string"},
                "day_name": {"type": "string", "description": _DAY_NAME_DESCRIPTION},
                "party_size": {"type": "integer"},
                "special_requests": {
                    "type": "string",
                    "description": "Replacement notes for the reservation (allergies, occasions, seating preferences).",
                },
            },
            "required": ["reservation_id", "phone_number"],
        },
    },
    {
        "name": "cancel_reservation",
        "description": "Cancel an existing reservation belonging to the calling phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reservation_id": {"type": "string"},
                "phone_number": {"type": "string"},
            },
            "required": ["reservation_id", "phone_number"],
        },
    },
    {
        "name": "confirm_phone_number",
        "description": (
            "Record whether the caller confirmed 'yes' or 'no' after you read "
            "their phone number back to them digit by digit. Call this every "
            "time you get a yes/no answer to that read-back — never track "
            "confirmation attempts yourself. If the result says attempts_left "
            "is 0, stop asking: tell the caller you're having trouble "
            "confirming the number and call escalate_to_staff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string", "description": "The number as read back to the caller."},
                "confirmed": {"type": "boolean", "description": "True if the caller said it's correct."},
            },
            "required": ["phone_number", "confirmed"],
        },
    },
    {
        "name": "escalate_to_staff",
        "description": "Transfer the live call to a human staff member — use immediately if your first attempt to help fails, or if the caller explicitly asks for a person.",
        "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    },
    {
        "name": "end_call",
        "description": (
            "Hang up the phone call. Use only after you have said goodbye and "
            "the caller's request is complete (e.g. booking confirmed) or they "
            "indicated they're done."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def find_customer(db: AsyncSession, phone_number: str) -> dict:
    customer = await customer_service.find_customer(db, phone_number)
    if customer is None:
        return {"found": False}
    return {
        "found": True,
        "customer_id": str(customer.id),
        "full_name": customer.full_name,
        "email": customer.email,
    }


async def check_availability(
    db: AsyncSession, starts_at: str, party_size: int, day_name: str | None = None
) -> dict:
    parsed_starts_at = datetime.fromisoformat(starts_at)
    mismatch = _weekday_mismatch(parsed_starts_at, day_name)
    if mismatch is not None:
        return mismatch

    availability = await reservation_service.check_availability(db, parsed_starts_at, party_size)
    result = {
        "available": availability.available,
        "seats_remaining": availability.remaining,
        "weekday": _local_weekday(parsed_starts_at),
    }
    if availability.closed_reason is not None:
        result["closed"] = True
        result["reason"] = availability.closed_reason
    return result


async def create_reservation(
    db: AsyncSession,
    phone_number: str,
    party_size: int,
    starts_at: str,
    customer_name: str | None = None,
    special_requests: str | None = None,
    day_name: str | None = None,
) -> dict:
    parsed_starts_at = datetime.fromisoformat(starts_at)
    mismatch = _weekday_mismatch(parsed_starts_at, day_name)
    if mismatch is not None:
        return mismatch

    customer = await customer_service.get_or_create_customer(db, phone_number, full_name=customer_name)
    try:
        reservation = await reservation_service.create_reservation(
            db,
            customer_id=customer.id,
            party_size=party_size,
            starts_at=parsed_starts_at,
            special_requests=special_requests,
        )
    except reservation_service.ReservationConflict as exc:
        await db.rollback()
        return {"success": False, "error": str(exc)}

    await db.commit()
    return {
        "success": True,
        "reservation_id": str(reservation.id),
        "weekday": _local_weekday(parsed_starts_at),
    }


async def find_reservations(db: AsyncSession, phone_number: str) -> dict:
    """Returns starts_at in restaurant-local time with its UTC offset —
    rows come back from the DB as UTC-aware datetimes (asyncpg normalizes
    TIMESTAMPTZ to UTC), and handing that straight to the agent as
    isoformat() previously made it misread booking times by the local UTC
    offset (and sometimes the calendar day)."""
    tz = ZoneInfo(get_settings().restaurant_timezone)
    reservations = await reservation_service.list_upcoming_reservations(db, phone_number)
    return {
        "reservations": [
            {
                "reservation_id": str(r.id),
                "starts_at": r.starts_at.astimezone(tz).isoformat(),
                "weekday": r.starts_at.astimezone(tz).strftime("%A"),
                "party_size": r.party_size,
                "special_requests": r.special_requests,
            }
            for r in reservations
        ]
    }


async def modify_reservation(
    db: AsyncSession,
    reservation_id: str,
    phone_number: str,
    starts_at: str | None = None,
    party_size: int | None = None,
    special_requests: str | None = None,
    day_name: str | None = None,
) -> dict:
    parsed_starts_at = datetime.fromisoformat(starts_at) if starts_at else None
    if parsed_starts_at is not None:
        mismatch = _weekday_mismatch(parsed_starts_at, day_name)
        if mismatch is not None:
            return mismatch

    try:
        reservation = await reservation_service.modify_reservation(
            db,
            reservation_id=UUID(reservation_id),
            requesting_phone_number=phone_number,
            starts_at=parsed_starts_at,
            party_size=party_size,
            special_requests=special_requests,
        )
    except PermissionError:
        return {"success": False, "error": "No matching reservation found for this phone number."}
    except reservation_service.ReservationConflict as exc:
        await db.rollback()
        return {"success": False, "error": str(exc)}

    await db.commit()
    result = {"success": True, "reservation_id": str(reservation.id)}
    if parsed_starts_at is not None:
        result["weekday"] = _local_weekday(parsed_starts_at)
    return result


async def cancel_reservation(db: AsyncSession, reservation_id: str, phone_number: str) -> dict:
    try:
        reservation = await reservation_service.cancel_reservation(
            db, reservation_id=UUID(reservation_id), requesting_phone_number=phone_number
        )
    except PermissionError:
        return {"success": False, "error": "No matching reservation found for this phone number."}

    await db.commit()
    return {"success": True, "reservation_id": str(reservation.id)}


MAX_PHONE_CONFIRMATION_ATTEMPTS = 3


async def confirm_phone_number(call_state: dict, phone_number: str, confirmed: bool) -> dict:
    """Tracks confirmation attempts in call_state (a dict that lives for the
    whole call, passed in by reservation_agent) rather than trusting the
    model to count its own retries. Caps at MAX_PHONE_CONFIRMATION_ATTEMPTS
    failed attempts so a caller who can't be understood doesn't loop forever."""
    if confirmed:
        call_state["phone_confirmation_attempts"] = 0
        return {"confirmed": True}

    call_state["phone_confirmation_attempts"] = call_state.get("phone_confirmation_attempts", 0) + 1
    attempts_left = max(MAX_PHONE_CONFIRMATION_ATTEMPTS - call_state["phone_confirmation_attempts"], 0)
    return {"confirmed": False, "attempts_left": attempts_left}


async def escalate_to_staff(reason: str) -> dict:
    # media_stream.py inspects this tool call and triggers the same TwiML
    # <Dial> transfer used for escalating a live call to staff.
    return {"escalate": True, "reason": reason}


async def end_call() -> dict:
    # media_stream.py inspects this and hangs up once the goodbye audio has
    # finished playing.
    return {"end_call": True}


DISPATCH = {
    "find_customer": find_customer,
    "check_availability": check_availability,
    "create_reservation": create_reservation,
    "find_reservations": find_reservations,
    "modify_reservation": modify_reservation,
    "cancel_reservation": cancel_reservation,
    "confirm_phone_number": confirm_phone_number,
    "escalate_to_staff": escalate_to_staff,
    "end_call": end_call,
}
