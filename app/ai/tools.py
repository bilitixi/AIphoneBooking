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


async def check_availability(db: AsyncSession, starts_at: str, party_size: int) -> dict:
    availability = await reservation_service.check_availability(
        db, datetime.fromisoformat(starts_at), party_size
    )
    result = {"available": availability.available, "seats_remaining": availability.remaining}
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
) -> dict:
    customer = await customer_service.get_or_create_customer(db, phone_number, full_name=customer_name)
    try:
        reservation = await reservation_service.create_reservation(
            db,
            customer_id=customer.id,
            party_size=party_size,
            starts_at=datetime.fromisoformat(starts_at),
            special_requests=special_requests,
        )
    except reservation_service.ReservationConflict as exc:
        await db.rollback()
        return {"success": False, "error": str(exc)}

    await db.commit()
    return {"success": True, "reservation_id": str(reservation.id)}


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
) -> dict:
    try:
        reservation = await reservation_service.modify_reservation(
            db,
            reservation_id=UUID(reservation_id),
            requesting_phone_number=phone_number,
            starts_at=datetime.fromisoformat(starts_at) if starts_at else None,
            party_size=party_size,
            special_requests=special_requests,
        )
    except PermissionError:
        return {"success": False, "error": "No matching reservation found for this phone number."}
    except reservation_service.ReservationConflict as exc:
        await db.rollback()
        return {"success": False, "error": str(exc)}

    await db.commit()
    return {"success": True, "reservation_id": str(reservation.id)}


async def cancel_reservation(db: AsyncSession, reservation_id: str, phone_number: str) -> dict:
    try:
        reservation = await reservation_service.cancel_reservation(
            db, reservation_id=UUID(reservation_id), requesting_phone_number=phone_number
        )
    except PermissionError:
        return {"success": False, "error": "No matching reservation found for this phone number."}

    await db.commit()
    return {"success": True, "reservation_id": str(reservation.id)}


async def escalate_to_staff(reason: str) -> dict:
    # media_stream.py inspects this tool call and triggers the same TwiML
    # <Dial> transfer used for the takeaway IVR path.
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
    "escalate_to_staff": escalate_to_staff,
    "end_call": end_call,
}
