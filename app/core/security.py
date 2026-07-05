from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from twilio.request_validator import RequestValidator

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


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


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def require_admin_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Dependency for admin-portal REST routes: validates the bearer JWT."""
    settings = get_settings()
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return subject
