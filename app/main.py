import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin_users, auth, calls, capacity_limits, customers, reservations
from app.core.config import get_settings
from app.core.cron import run_reservation_cleanup_loop
from app.core.logging import configure_logging
from app.phone import incoming, ivr, media_stream

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(run_reservation_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()


app = FastAPI(title="ABC Restaurant Backend", lifespan=lifespan)

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
app.include_router(admin_users.router)
app.include_router(reservations.router)
app.include_router(customers.router)
app.include_router(capacity_limits.router)
app.include_router(calls.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
