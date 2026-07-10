from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user
from app.db.models import PhoneCall
from app.db.session import get_db

router = APIRouter(prefix="/api/calls", tags=["calls"], dependencies=[Depends(require_admin_user)])


class PhoneCallOut(BaseModel):
    id: UUID
    call_sid: str
    from_number: str
    ivr_choice: str | None
    outcome: str | None
    started_at: datetime
    ended_at: datetime | None

    class Config:
        from_attributes = True


@router.get("", response_model=list[PhoneCallOut])
async def list_calls(db: AsyncSession = Depends(get_db)) -> list[PhoneCall]:
    result = await db.execute(select(PhoneCall).order_by(PhoneCall.started_at.desc()))
    return list(result.scalars().all())
