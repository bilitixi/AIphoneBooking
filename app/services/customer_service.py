from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer


async def find_customer(db: AsyncSession, phone_number: str) -> Customer | None:
    result = await db.execute(select(Customer).where(Customer.phone_number == phone_number))
    return result.scalar_one_or_none()


async def get_or_create_customer(
    db: AsyncSession, phone_number: str, full_name: str | None = None
) -> Customer:
    customer = await find_customer(db, phone_number)
    if customer is not None:
        return customer

    customer = Customer(phone_number=phone_number, full_name=full_name)
    db.add(customer)
    await db.flush()
    return customer
