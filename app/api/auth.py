from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn) -> TokenOut:
    settings = get_settings()
    valid = payload.username == settings.admin_username and verify_password(
        payload.password, settings.admin_password_hash
    )
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(subject=payload.username)
    return TokenOut(access_token=token)
