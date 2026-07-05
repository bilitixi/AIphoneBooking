from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user
from app.db.models import CallLog, PhoneCall
from app.db.session import get_db

router = APIRouter(prefix="/api/call-logs", tags=["call_logs"], dependencies=[Depends(require_admin_user)])


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


class CallLogEntryOut(BaseModel):
    id: UUID
    role: str
    content: str
    tool_name: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/calls", response_model=list[PhoneCallOut])
async def list_calls(db: AsyncSession = Depends(get_db)) -> list[PhoneCall]:
    result = await db.execute(select(PhoneCall).order_by(PhoneCall.started_at.desc()))
    return list(result.scalars().all())


@router.get("/calls/{call_id}/transcript", response_model=list[CallLogEntryOut])
async def get_call_transcript(call_id: UUID, db: AsyncSession = Depends(get_db)) -> list[CallLog]:
    call = await db.get(PhoneCall, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")

    result = await db.execute(
        select(CallLog).where(CallLog.call_id == call_id).order_by(CallLog.created_at)
    )
    return list(result.scalars().all())
