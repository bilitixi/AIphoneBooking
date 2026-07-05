from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reservation, RestaurantTable

DEFAULT_SEATING_DURATION = timedelta(hours=2)


@dataclass
class TableOption:
    table_id: UUID
    label: str
    seats: int


class ReservationConflict(Exception):
    """Raised when the requested slot was taken between the availability
    check and the insert — the caller should offer alternatives, not retry
    blindly."""


async def check_tables(
    db: AsyncSession, starts_at: datetime, party_size: int, duration: timedelta = DEFAULT_SEATING_DURATION
) -> list[TableOption]:
    """Best-effort availability read. This is advisory only — the real
    guarantee comes from the DB exclusion constraint at insert time, since
    availability can change between this read and create_reservation."""
    ends_at = starts_at + duration

    overlapping_table_ids = (
        select(Reservation.table_id)
        .where(
            Reservation.status == "confirmed",
            Reservation.starts_at < ends_at,
            Reservation.ends_at > starts_at,
        )
    )

    result = await db.execute(
        select(RestaurantTable)
        .where(
            RestaurantTable.active.is_(True),
            RestaurantTable.seats >= party_size,
            RestaurantTable.id.not_in(overlapping_table_ids),
        )
        .order_by(RestaurantTable.seats.asc())
    )
    tables = result.scalars().all()
    return [TableOption(table_id=t.id, label=t.label, seats=t.seats) for t in tables]


async def create_reservation(
    db: AsyncSession,
    customer_id: UUID,
    table_id: UUID,
    party_size: int,
    starts_at: datetime,
    duration: timedelta = DEFAULT_SEATING_DURATION,
    source: str = "ai_call",
    special_requests: str | None = None,
) -> Reservation:
    """The single place that matters for concurrency: attempt the insert and
    let the DB's exclusion constraint be the source of truth. A prior
    check_tables() read can be stale by the time this runs (another caller,
    AI or staff, may have booked the same table in between)."""
    reservation = Reservation(
        customer_id=customer_id,
        table_id=table_id,
        party_size=party_size,
        starts_at=starts_at,
        ends_at=starts_at + duration,
        source=source,
        special_requests=special_requests,
    )
    db.add(reservation)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        orig = getattr(exc, "orig", None)
        cause = getattr(orig, "__cause__", None)
        if isinstance(cause, asyncpg.exceptions.ExclusionViolationError):
            raise ReservationConflict(
                "That time just got booked on this table."
            ) from exc
        raise
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

    for field in ("starts_at", "ends_at", "party_size", "table_id", "special_requests"):
        if field in updates and updates[field] is not None:
            setattr(reservation, field, updates[field])

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        orig = getattr(exc, "orig", None)
        cause = getattr(orig, "__cause__", None)
        if isinstance(cause, asyncpg.exceptions.ExclusionViolationError):
            raise ReservationConflict("That time just got booked on this table.") from exc
        raise
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
