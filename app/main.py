from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, calls, capacity_limits, customers, reservations
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.phone import incoming, ivr, media_stream

configure_logging()

app = FastAPI(title="ABC Restaurant Backend")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incoming.router)
app.include_router(ivr.router)
app.include_router(media_stream.router)

app.include_router(auth.router)
app.include_router(reservations.router)
app.include_router(customers.router)
app.include_router(capacity_limits.router)
app.include_router(calls.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
