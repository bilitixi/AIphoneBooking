from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CapacityLimit, Reservation

DEFAULT_SEATING_DURATION = timedelta(hours=2)

# Serializes capacity checks + inserts across workers. Capacity is a SUM over
# rows, which no unique/exclusion constraint can enforce, so writers take this
# advisory lock for the duration of their transaction instead.
_CAPACITY_LOCK_KEY = 0x5EA75


@dataclass
class Availability:
    available: bool
    remaining: int  # seats left in the requested window (0 if full)
    limit: int  # effective capacity for the window


class ReservationConflict(Exception):
    """Raised when the requested window can't seat the party — either it was
    full to begin with or filled up between the availability check and the
    insert. The caller should offer alternatives, not retry blindly."""


async def _effective_limit(db: AsyncSession, starts_at: datetime, ends_at: datetime) -> int:
    """Capacity for a window: the default from settings, unless one or more
    staff-defined capacity_limits windows overlap — then the lowest cap wins."""
    result = await db.execute(
        select(func.min(CapacityLimit.max_customers)).where(
            CapacityLimit.starts_at < ends_at,
            CapacityLimit.ends_at > starts_at,
        )
    )
    override = result.scalar_one()
    default = get_settings().restaurant_default_capacity
    return min(default, override) if override is not None else default


async def _seated_count(
    db: AsyncSession, starts_at: datetime, ends_at: datetime, exclude_reservation_id: UUID | None = None
) -> int:
    query = select(func.coalesce(func.sum(Reservation.party_size), 0)).where(
        Reservation.status == "confirmed",
        Reservation.starts_at < ends_at,
        Reservation.ends_at > starts_at,
    )
    if exclude_reservation_id is not None:
        query = query.where(Reservation.id != exclude_reservation_id)
    result = await db.execute(query)
    return result.scalar_one()


async def check_availability(
    db: AsyncSession, starts_at: datetime, party_size: int, duration: timedelta = DEFAULT_SEATING_DURATION
) -> Availability:
    """Best-effort availability read. Advisory only — the authoritative check
    happens under the advisory lock in create_reservation, since availability
    can change between this read and the insert."""
    ends_at = starts_at + duration
    limit = await _effective_limit(db, starts_at, ends_at)
    seated = await _seated_count(db, starts_at, ends_at)
    remaining = max(limit - seated, 0)
    return Availability(available=party_size <= remaining, remaining=remaining, limit=limit)


async def _assert_capacity(
    db: AsyncSession,
    starts_at: datetime,
    ends_at: datetime,
    party_size: int,
    exclude_reservation_id: UUID | None = None,
) -> None:
    """Takes the capacity advisory lock (held until commit/rollback) and
    verifies the party fits. Must be called inside the writing transaction."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CAPACITY_LOCK_KEY})
    limit = await _effective_limit(db, starts_at, ends_at)
    seated = await _seated_count(db, starts_at, ends_at, exclude_reservation_id)
    if seated + party_size > limit:
        remaining = max(limit - seated, 0)
        raise ReservationConflict(
            f"That time can seat {remaining} more customer(s) at most, which doesn't fit a party of {party_size}."
        )


async def create_reservation(
    db: AsyncSession,
    customer_id: UUID,
    party_size: int,
    starts_at: datetime,
    duration: timedelta = DEFAULT_SEATING_DURATION,
    source: str = "ai_call",
    special_requests: str | None = None,
) -> Reservation:
    ends_at = starts_at + duration
    await _assert_capacity(db, starts_at, ends_at, party_size)

    reservation = Reservation(
        customer_id=customer_id,
        party_size=party_size,
        starts_at=starts_at,
        ends_at=ends_at,
        source=source,
        special_requests=special_requests,
    )
    db.add(reservation)
    await db.flush()
    return reservation


async def modify_reservation(
    db: AsyncSession,
    reservation_id: UUID,
    requesting_phone_number: str | None,
    **updates,
) -> Reservation:
    """`requesting_phone_number=None` bypasses the ownership check — used by
    the JWT-authenticated admin portal, which is trusted differently than
    an anonymous phone call."""
    reservation = await _get_reservation(db, reservation_id, requesting_phone_number)

    for field in ("starts_at", "ends_at", "party_size", "special_requests"):
        if field in updates and updates[field] is not None:
            setattr(reservation, field, updates[field])
    if "starts_at" in updates and updates["starts_at"] is not None and "ends_at" not in updates:
        reservation.ends_at = reservation.starts_at + DEFAULT_SEATING_DURATION

    await _assert_capacity(
        db,
        reservation.starts_at,
        reservation.ends_at,
        reservation.party_size,
        exclude_reservation_id=reservation.id,
    )
    await db.flush()
    return reservation


async def cancel_reservation(
    db: AsyncSession, reservation_id: UUID, requesting_phone_number: str | None
) -> Reservation:
    reservation = await _get_reservation(db, reservation_id, requesting_phone_number)
    reservation.status = "cancelled"
    await db.flush()
    return reservation


async def _get_reservation(
    db: AsyncSession, reservation_id: UUID, requesting_phone_number: str | None
) -> Reservation:
    """Enforces that a phone caller can only modify/cancel their own
    reservation. `requesting_phone_number=None` skips that check for the
    already-authenticated admin portal."""
    from app.db.models import Customer  # local import to avoid a cycle at module load

    query = select(Reservation).where(Reservation.id == reservation_id)
    if requesting_phone_number is not None:
        query = query.join(Customer, Reservation.customer_id == Customer.id).where(
            Customer.phone_number == requesting_phone_number
        )

    result = await db.execute(query)
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise PermissionError("Reservation not found for this phone number")
    return reservation
