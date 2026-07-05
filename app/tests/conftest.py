import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/abc_restaurant_test")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.core.config import get_settings


@pytest_asyncio.fixture
async def db_session():
    """Integration fixture — requires a real Postgres reachable at
    DATABASE_URL (btree_gist extension needs actual Postgres, not sqlite)."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    try:
        async with engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"Postgres not reachable at {settings.database_url}: {exc}")

    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            __import__("sqlalchemy").text(
                """
                ALTER TABLE reservations
                ADD CONSTRAINT excl_reservations_no_overlap
                EXCLUDE USING gist (
                    table_id WITH =,
                    tstzrange(starts_at, ends_at) WITH &&
                ) WHERE (status = 'confirmed')
                """
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
