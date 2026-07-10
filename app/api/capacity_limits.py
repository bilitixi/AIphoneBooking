from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user, require_manager
from app.db.models import CapacityLimit
from app.db.session import get_db

router = APIRouter(
    prefix="/api/capacity-limits", tags=["capacity-limits"], dependencies=[Depends(require_admin_user)]
)


class CapacityLimitOut(BaseModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    max_customers: int
    note: str | None

    class Config:
        from_attributes = True


class CreateCapacityLimitIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    max_customers: int
    note: str | None = None


class UpdateCapacityLimitIn(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_customers: int | None = None
    note: str | None = None


@router.get("", response_model=list[CapacityLimitOut])
async def list_capacity_limits(db: AsyncSession = Depends(get_db)) -> list[CapacityLimit]:
    result = await db.execute(select(CapacityLimit).order_by(CapacityLimit.starts_at))
    return list(result.scalars().all())


@router.post("", response_model=CapacityLimitOut, status_code=201)
async def create_capacity_limit(
    payload: CreateCapacityLimitIn, db: AsyncSession = Depends(get_db)
) -> CapacityLimit:
    limit = CapacityLimit(**payload.model_dump())
    db.add(limit)
    await db.commit()
    await db.refresh(limit)
    return limit


@router.patch("/{limit_id}", response_model=CapacityLimitOut)
async def update_capacity_limit(
    limit_id: UUID, payload: UpdateCapacityLimitIn, db: AsyncSession = Depends(get_db)
) -> CapacityLimit:
    limit = await db.get(CapacityLimit, limit_id)
    if limit is None:
        raise HTTPException(status_code=404, detail="Capacity limit not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(limit, field, value)

    await db.commit()
    await db.refresh(limit)
    return limit


@router.delete("/{limit_id}", status_code=204, dependencies=[Depends(require_manager)])
async def delete_capacity_limit(limit_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    limit = await db.get(CapacityLimit, limit_id)
    if limit is None:
        raise HTTPException(status_code=404, detail="Capacity limit not found")
    await db.delete(limit)
    await db.commit()


@router.delete("", status_code=204, dependencies=[Depends(require_manager)])
async def delete_capacity_limits(
    confirm: bool = Query(
        False, description="Must be true to permanently delete ALL capacity limits"
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Bulk delete-all counterpart to delete_capacity_limit above (which \
    already handles deleting a single limit by id)."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete ALL capacity limits")
    await db.execute(delete(CapacityLimit))
    await db.commit()
