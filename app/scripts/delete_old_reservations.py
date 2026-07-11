"""One-shot cleanup: permanently deletes reservations older than the
retention window (default 7 days, see RESERVATION_RETENTION).

Usage:
    python -m app.scripts.delete_old_reservations

Runs once and exits, so it can be driven either by the in-process daily
cron started in app.main (see app/core/cron.py) or by an external
scheduler (OS crontab, k8s CronJob, etc) if you'd rather manage it outside
the app process.
"""
import asyncio
import logging

from app.db.session import async_session_factory
from app.services import reservation_service

logger = logging.getLogger(__name__)


async def delete_old_reservations() -> int:
    async with async_session_factory() as db:
        deleted = await reservation_service.delete_stale_reservations(db)
        await db.commit()
        return deleted


def main() -> None:
    deleted = asyncio.run(delete_old_reservations())
    print(f"Deleted {deleted} reservation(s) older than {reservation_service.RESERVATION_RETENTION.days} days")


if __name__ == "__main__":
    main()
