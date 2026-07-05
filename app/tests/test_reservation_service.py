import asyncio
from datetime import datetime, timezone

import pytest

from app.db.models import Customer, RestaurantTable
from app.services import reservation_service

pytestmark = pytest.mark.asyncio


async def _make_customer_and_table(db, phone="+6421000000"):
    customer = Customer(phone_number=phone)
    table = RestaurantTable(label="T1", seats=4)
    db.add_all([customer, table])
    await db.flush()
    return customer, table


async def test_create_reservation_succeeds(db_session):
    customer, table = await _make_customer_and_table(db_session)
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    assert reservation.id is not None
    assert reservation.status == "confirmed"


async def test_create_reservation_overlap_is_rejected(db_session):
    customer, table = await _make_customer_and_table(db_session)
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

    await reservation_service.create_reservation(
        db_session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    with pytest.raises(reservation_service.ReservationConflict):
        await reservation_service.create_reservation(
            db_session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
        )


async def test_check_tables_excludes_booked_table(db_session):
    customer, table = await _make_customer_and_table(db_session)
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

    await reservation_service.create_reservation(
        db_session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
    )
    await db_session.commit()

    options = await reservation_service.check_tables(db_session, starts_at, party_size=2)
    assert table.id not in [o.table_id for o in options]


async def test_cancel_reservation_requires_matching_phone_number(db_session):
    customer, table = await _make_customer_and_table(db_session, phone="+6421111111")
    starts_at = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)

    reservation = await reservation_service.create_reservation(
        db_session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
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


async def test_concurrent_creates_only_one_wins(db_session):
    """Simulates two callers racing for the same slot on separate DB
    connections — only one insert should succeed, proving the DB exclusion
    constraint (not app-level locking) is what prevents double-booking."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    customer, table = await _make_customer_and_table(db_session)
    await db_session.commit()
    starts_at = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def attempt():
        async with session_factory() as session:
            reservation = await reservation_service.create_reservation(
                session, customer_id=customer.id, table_id=table.id, party_size=2, starts_at=starts_at
            )
            await session.commit()
            return reservation

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

    successes = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, reservation_service.ReservationConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
