from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user
from app.db.models import RestaurantTable
from app.db.session import get_db

router = APIRouter(prefix="/api/tables", tags=["tables"], dependencies=[Depends(require_admin_user)])


class TableOut(BaseModel):
    id: UUID
    label: str
    seats: int
    active: bool

    class Config:
        from_attributes = True


class CreateTableIn(BaseModel):
    label: str
    seats: int


class UpdateTableIn(BaseModel):
    label: str | None = None
    seats: int | None = None
    active: bool | None = None


@router.get("", response_model=list[TableOut])
async def list_tables(db: AsyncSession = Depends(get_db)) -> list[RestaurantTable]:
    result = await db.execute(select(RestaurantTable).order_by(RestaurantTable.label))
    return list(result.scalars().all())


@router.post("", response_model=TableOut, status_code=201)
async def create_table(payload: CreateTableIn, db: AsyncSession = Depends(get_db)) -> RestaurantTable:
    table = RestaurantTable(label=payload.label, seats=payload.seats)
    db.add(table)
    await db.commit()
    await db.refresh(table)
    return table


@router.patch("/{table_id}", response_model=TableOut)
async def update_table(table_id: UUID, payload: UpdateTableIn, db: AsyncSession = Depends(get_db)) -> RestaurantTable:
    table = await db.get(RestaurantTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(table, field, value)

    await db.commit()
    await db.refresh(table)
    return table
