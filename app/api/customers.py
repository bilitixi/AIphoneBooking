from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user, require_manager
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


@router.delete("", status_code=204, dependencies=[Depends(require_manager)])
async def delete_customers(
    customer_id: UUID | None = Query(None, description="Permanently delete only this customer"),
    confirm: bool = Query(
        False, description="Must be true to permanently delete ALL customers when customer_id is omitted"
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deleting a customer cascades to their reservations (FK ondelete=CASCADE)."""
    if customer_id is not None:
        result = await db.execute(delete(Customer).where(Customer.id == customer_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Customer not found")
    else:
        if not confirm:
            raise HTTPException(
                status_code=400, detail="Pass confirm=true to delete ALL customers, or customer_id to delete one"
            )
        await db.execute(delete(Customer))
    await db.commit()
