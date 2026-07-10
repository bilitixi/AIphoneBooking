from fastapi import FastAPI

from app.api import calls, capacity_limits, customers, reservations
from app.core.logging import configure_logging
from app.phone import incoming, ivr, media_stream

configure_logging()

app = FastAPI(title="ABC Restaurant Backend")

app.include_router(incoming.router)
app.include_router(ivr.router)
app.include_router(media_stream.router)

app.include_router(reservations.router)
app.include_router(customers.router)
app.include_router(capacity_limits.router)
app.include_router(calls.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
