from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user
from app.db.models import Customer
from app.db.session import get_db

router = APIRouter(prefix="/api/customers", tags=["customers"], dependencies=[Depends(require_admin_user)])


class CustomerOut(BaseModel):
    id: UUID
    phone_number: str
    full_name: str | None
    email: str | None
    notes: str | None

    class Config:
        from_attributes = True


class UpdateCustomerIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    notes: str | None = None


@router.get("", response_model=list[CustomerOut])
async def list_customers(db: AsyncSession = Depends(get_db)) -> list[Customer]:
    result = await db.execute(select(Customer).order_by(Customer.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: UUID, payload: UpdateCustomerIn, db: AsyncSession = Depends(get_db)
) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)

    await db.commit()
    await db.refresh(customer)
    return customer
