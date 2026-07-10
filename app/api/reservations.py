from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_admin_user, require_manager
from app.db.models import Reservation
from app.db.session import get_db
from app.services import reservation_service

router = APIRouter(prefix="/api/reservations", tags=["reservations"], dependencies=[Depends(require_admin_user)])


class ReservationOut(BaseModel):
    id: UUID
    customer_id: UUID
    party_size: int
    starts_at: datetime
    ends_at: datetime
    status: str
    source: str
    special_requests: str | None

    class Config:
        from_attributes = True


class CreateReservationIn(BaseModel):
    customer_id: UUID
    party_size: int
    starts_at: datetime
    special_requests: str | None = None


class UpdateReservationIn(BaseModel):
    starts_at: datetime | None = None
    party_size: int | None = None
    special_requests: str | None = None


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    date: date | None = Query(None, description="Restaurant-local date (YYYY-MM-DD); returns that day's reservations"),
    status: str | None = Query(None, description="Filter by status (e.g. confirmed, cancelled)"),
    customer_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[Reservation]:
    stmt = select(Reservation).order_by(Reservation.starts_at.desc())

    if date is not None:
        tz = ZoneInfo(get_settings().restaurant_timezone)
        day_start = datetime.combine(date, datetime.min.time(), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        stmt = stmt.where(Reservation.starts_at >= day_start, Reservation.starts_at < day_end)

    if status is not None:
        stmt = stmt.where(Reservation.status == status)

    if customer_id is not None:
        stmt = stmt.where(Reservation.customer_id == customer_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{reservation_id}", response_model=ReservationOut)
async def get_reservation(reservation_id: UUID, db: AsyncSession = Depends(get_db)) -> Reservation:
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@router.post("", response_model=ReservationOut, status_code=201)
async def create_reservation(payload: CreateReservationIn, db: AsyncSession = Depends(get_db)) -> Reservation:
    try:
        reservation = await reservation_service.create_reservation(
            db,
            customer_id=payload.customer_id,
            party_size=payload.party_size,
            starts_at=payload.starts_at,
            source="staff_portal",
            special_requests=payload.special_requests,
        )
    except reservation_service.ReservationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationOut)
async def update_reservation(
    reservation_id: UUID, payload: UpdateReservationIn, db: AsyncSession = Depends(get_db)
) -> Reservation:
    try:
        reservation = await reservation_service.modify_reservation(
            db,
            reservation_id=reservation_id,
            requesting_phone_number=None,
            **payload.model_dump(exclude_unset=True),
        )
    except PermissionError:
        raise HTTPException(status_code=404, detail="Reservation not found")
    except reservation_service.ReservationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    return reservation


@router.delete("/{reservation_id}", response_model=ReservationOut)
async def cancel_reservation(reservation_id: UUID, db: AsyncSession = Depends(get_db)) -> Reservation:
    try:
        reservation = await reservation_service.cancel_reservation(
            db, reservation_id=reservation_id, requesting_phone_number=None
        )
    except PermissionError:
        raise HTTPException(status_code=404, detail="Reservation not found")
    await db.commit()
    return reservation


@router.delete("", status_code=204, dependencies=[Depends(require_manager)])
async def delete_reservations(
    reservation_id: UUID | None = Query(None, description="Permanently delete only this reservation"),
    confirm: bool = Query(
        False, description="Must be true to permanently delete ALL reservations when reservation_id is omitted"
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Manager-only hard delete — permanently removes rows, unlike the \
    cancel endpoint above which just marks status='cancelled'."""
    if reservation_id is not None:
        result = await db.execute(delete(Reservation).where(Reservation.id == reservation_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Reservation not found")
    else:
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Pass confirm=true to delete ALL reservations, or reservation_id to delete one",
            )
        await db.execute(delete(Reservation))
    await db.commit()
