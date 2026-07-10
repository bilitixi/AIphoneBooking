from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from twilio.request_validator import RequestValidator

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AdminIdentity:
    id: str
    role: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


async def verify_twilio_signature(request: Request) -> None:
    """Reject any /phone/* webhook whose X-Twilio-Signature doesn't match.

    Twilio signs the exact URL + form body, so this must run before the
    body is otherwise parsed/mutated.
    """
    settings = get_settings()
    validator = RequestValidator(settings.twilio_auth_token)

    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    url = str(request.url)

    if not validator.validate(url, dict(form), signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def require_admin_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AdminIdentity:
    """Dependency for admin-portal REST routes: validates the bearer JWT."""
    settings = get_settings()
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    subject = payload.get("sub")
    role = payload.get("role")
    if not subject or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return AdminIdentity(id=subject, role=role)


async def require_manager(
    identity: AdminIdentity = Depends(require_admin_user),
) -> AdminIdentity:
    """Dependency for routes only managers may use (e.g. managing admin_users)."""
    if identity.role != "manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager role required")
    return identity
