from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user
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
async def list_reservations(db: AsyncSession = Depends(get_db)) -> list[Reservation]:
    result = await db.execute(select(Reservation).order_by(Reservation.starts_at.desc()))
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
