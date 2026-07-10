from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AdminIdentity, hash_password, require_manager
from app.db.models import AdminUser
from app.db.session import get_db

router = APIRouter(prefix="/api/admin-users", tags=["admin-users"], dependencies=[Depends(require_manager)])


class AdminUserOut(BaseModel):
    id: UUID
    username: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class CreateAdminUserIn(BaseModel):
    username: str
    password: str
    role: str = "staff"


class UpdateAdminUserIn(BaseModel):
    role: str | None = None
    is_active: bool | None = None


VALID_ROLES = {"manager", "staff"}


@router.get("", response_model=list[AdminUserOut])
async def list_admin_users(db: AsyncSession = Depends(get_db)) -> list[AdminUser]:
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at))
    return list(result.scalars().all())


@router.post("", response_model=AdminUserOut, status_code=201)
async def create_admin_user(payload: CreateAdminUserIn, db: AsyncSession = Depends(get_db)) -> AdminUser:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(VALID_ROLES)}")

    existing = await db.execute(select(AdminUser).where(AdminUser.username == payload.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    admin = AdminUser(username=payload.username, password_hash=hash_password(payload.password), role=payload.role)
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


@router.patch("/{admin_id}", response_model=AdminUserOut)
async def update_admin_user(
    admin_id: UUID, payload: UpdateAdminUserIn, db: AsyncSession = Depends(get_db)
) -> AdminUser:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin user not found")

    updates = payload.model_dump(exclude_unset=True)
    if "role" in updates and updates["role"] not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(VALID_ROLES)}")

    for field, value in updates.items():
        setattr(admin, field, value)

    await db.commit()
    await db.refresh(admin)
    return admin


@router.delete("/{admin_id}", status_code=204)
async def delete_admin_user(
    admin_id: UUID,
    identity: AdminIdentity = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
) -> None:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin user not found")

    if str(admin.id) == identity.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    if admin.role == "manager":
        result = await db.execute(
            select(func.count()).select_from(AdminUser).where(AdminUser.role == "manager")
        )
        if result.scalar_one() <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last manager")

    await db.delete(admin)
    await db.commit()
