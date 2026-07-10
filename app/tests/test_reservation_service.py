import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.config import get_settings
from app.db.models import CapacityLimit, Customer
from app.services import reservation_service

pytestmark = pytest.mark.asyncio

NZ = ZoneInfo(get_settings().restaurant_timezone)


async def _make_customer(db, phone="+6421000000"):
    customer = Customer(phone_number=phone)
    db.add(customer)
    await db.flush()
    return customer


async def test_create_reservation_succeeds(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner

    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    assert reservation.id is not None
    assert reservation.status == "confirmed"


async def test_create_reservation_stores_special_requests(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner

    reservation = await reservation_service.create_reservation(
        db_session,
        customer_id=customer.id,
        party_size=2,
        starts_at=starts_at,
        special_requests="Nut allergy; anniversary dinner",
    )
    await db_session.commit()

    assert reservation.special_requests == "Nut allergy; anniversary dinner"


async def test_capacity_limit_window_is_enforced(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner
    db_session.add(
        CapacityLimit(
            starts_at=starts_at - timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=3),
            max_customers=4,
            note="private event",
        )
    )
    await db_session.flush()

    await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=3, starts_at=starts_at
    )
    await db_session.commit()

    with pytest.raises(reservation_service.ReservationConflict):
        await reservation_service.create_reservation(
            db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
        )


async def test_check_availability_reflects_seated_count(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner
    db_session.add(
        CapacityLimit(
            starts_at=starts_at - timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=3),
            max_customers=10,
        )
    )
    await db_session.flush()

    await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=6, starts_at=starts_at
    )
    await db_session.commit()

    availability = await reservation_service.check_availability(db_session, starts_at, party_size=4)
    assert availability.available
    assert availability.remaining == 4

    availability = await reservation_service.check_availability(db_session, starts_at, party_size=5)
    assert not availability.available


def test_closed_reason_covers_opening_hours_rules():
    # 2026-08-02 is a Sunday, 2026-08-03 a Monday, 2026-08-01 a Saturday.
    sunday = datetime(2026, 8, 2, 19, 0, tzinfo=NZ)
    assert "Sunday" in reservation_service.closed_reason(sunday)

    weekday_break = datetime(2026, 8, 3, 15, 0, tzinfo=NZ)
    assert "closed between" in reservation_service.closed_reason(weekday_break)
    break_start_edge = datetime(2026, 8, 3, 14, 15, tzinfo=NZ)
    assert reservation_service.closed_reason(break_start_edge) is not None
    reopen_edge = datetime(2026, 8, 3, 17, 0, tzinfo=NZ)
    assert reservation_service.closed_reason(reopen_edge) is None

    too_late = datetime(2026, 8, 3, 21, 0, tzinfo=NZ)
    assert "last booking" in reservation_service.closed_reason(too_late)
    last_slot = datetime(2026, 8, 3, 20, 45, tzinfo=NZ)
    assert reservation_service.closed_reason(last_slot) is None

    # Saturday has no weekday break, but the last-booking cutoff still applies.
    saturday_afternoon = datetime(2026, 8, 1, 15, 0, tzinfo=NZ)
    assert reservation_service.closed_reason(saturday_afternoon) is None
    saturday_late = datetime(2026, 8, 1, 22, 0, tzinfo=NZ)
    assert "last booking" in reservation_service.closed_reason(saturday_late)


async def test_create_reservation_refused_when_closed(db_session):
    customer = await _make_customer(db_session)
    sunday = datetime(2026, 8, 2, 19, 0, tzinfo=NZ)

    with pytest.raises(reservation_service.ReservationConflict, match="Sunday"):
        await reservation_service.create_reservation(
            db_session, customer_id=customer.id, party_size=2, starts_at=sunday
        )


async def test_check_availability_reports_closed(db_session):
    weekday_break = datetime(2026, 8, 3, 14, 30, tzinfo=NZ)
    availability = await reservation_service.check_availability(db_session, weekday_break, party_size=2)
    assert not availability.available
    assert "closed between" in availability.closed_reason


async def test_list_upcoming_reservations_scoped_to_caller(db_session):
    customer = await _make_customer(db_session, phone="+6421222222")
    other = await _make_customer(db_session, phone="+6421333333")
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner

    mine = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
    )
    cancelled = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at + timedelta(days=1)
    )
    await reservation_service.create_reservation(
        db_session, customer_id=other.id, party_size=4, starts_at=starts_at
    )
    await db_session.commit()
    await reservation_service.cancel_reservation(
        db_session, reservation_id=cancelled.id, requesting_phone_number="+6421222222"
    )
    await db_session.commit()

    found = await reservation_service.list_upcoming_reservations(db_session, "+6421222222")
    assert [r.id for r in found] == [mine.id]


async def test_modify_reservation_updates_special_requests(db_session):
    customer = await _make_customer(db_session, phone="+6421444444")
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner
    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    updated = await reservation_service.modify_reservation(
        db_session,
        reservation_id=reservation.id,
        requesting_phone_number="+6421444444",
        special_requests="Table upstairs please",
    )
    await db_session.commit()
    assert updated.special_requests == "Table upstairs please"


async def test_cancel_reservation_requires_matching_phone_number(db_session):
    customer = await _make_customer(db_session, phone="+6421111111")
    starts_at = datetime(2026, 8, 3, 19, 0, tzinfo=NZ)  # Monday dinner

    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    with pytest.raises(PermissionError):
        await reservation_service.cancel_reservation(
            db_session, reservation_id=reservation.id, requesting_phone_number="+6429999999"
        )

    cancelled = await reservation_service.cancel_reservation(
        db_session, reservation_id=reservation.id, requesting_phone_number="+6421111111"
    )
    assert cancelled.status == "cancelled"


async def test_concurrent_creates_do_not_oversell_capacity(db_session):
    """Two callers race for the last seats on separate DB connections — the
    advisory lock in _assert_capacity must serialize them so only one fits."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 3, 20, 0, tzinfo=NZ)  # Monday dinner
    db_session.add(
        CapacityLimit(
            starts_at=starts_at - timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=3),
            max_customers=4,
        )
    )
    await db_session.commit()

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def attempt():
        async with session_factory() as session:
            reservation = await reservation_service.create_reservation(
                session, customer_id=customer.id, party_size=3, starts_at=starts_at
            )
            await session.commit()
            return reservation

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

    successes = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, reservation_service.ReservationConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
