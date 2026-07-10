from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_user, require_manager
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


@router.delete("", status_code=204, dependencies=[Depends(require_manager)])
async def delete_calls(
    call_id: UUID | None = Query(None, description="Permanently delete only this call record"),
    confirm: bool = Query(
        False, description="Must be true to permanently delete ALL call records when call_id is omitted"
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    if call_id is not None:
        result = await db.execute(delete(PhoneCall).where(PhoneCall.id == call_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Call not found")
    else:
        if not confirm:
            raise HTTPException(
                status_code=400, detail="Pass confirm=true to delete ALL calls, or call_id to delete one"
            )
        await db.execute(delete(PhoneCall))
    await db.commit()
