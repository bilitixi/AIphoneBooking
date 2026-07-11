"""In-process daily cron: purges reservations older than the retention
window (RESERVATION_RETENTION, default 7 days) every 24 hours. Started as
a background task from app.main's lifespan so a single uvicorn process is
enough — no external scheduler required."""
import asyncio
import logging

from app.db.session import async_session_factory
from app.services import reservation_service

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL = 60 * 60 * 24  # 24 hours


async def run_reservation_cleanup_loop() -> None:
    while True:
        try:
            async with async_session_factory() as db:
                deleted = await reservation_service.delete_stale_reservations(db)
                await db.commit()
            if deleted:
                logger.info("reservation cleanup: deleted %d stale reservation(s)", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reservation cleanup run failed")
        await asyncio.sleep(CLEANUP_INTERVAL)
