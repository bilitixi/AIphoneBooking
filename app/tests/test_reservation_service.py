import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import CapacityLimit, Customer
from app.services import reservation_service

pytestmark = pytest.mark.asyncio


async def _make_customer(db, phone="+6421000000"):
    customer = Customer(phone_number=phone)
    db.add(customer)
    await db.flush()
    return customer


async def test_create_reservation_succeeds(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    assert reservation.id is not None
    assert reservation.status == "confirmed"


async def test_create_reservation_stores_special_requests(db_session):
    customer = await _make_customer(db_session)
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

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
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)
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
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)
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


async def test_cancel_reservation_requires_matching_phone_number(db_session):
    customer = await _make_customer(db_session, phone="+6421111111")
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

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
    starts_at = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)
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
