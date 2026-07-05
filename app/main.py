from fastapi import FastAPI

from app.api import call_logs, customers, reservations, tables
from app.core.logging import configure_logging
from app.phone import incoming, ivr, media_stream

configure_logging()

app = FastAPI(title="ABC Restaurant Backend")

app.include_router(incoming.router)
app.include_router(ivr.router)
app.include_router(media_stream.router)

app.include_router(reservations.router)
app.include_router(customers.router)
app.include_router(tables.router)
app.include_router(call_logs.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
