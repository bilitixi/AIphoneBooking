"""seed restaurant tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10

Starter floor plan so availability checks have tables to offer. Idempotent:
skips labels that already exist, so it's safe on databases that were already
seeded via seed.sql.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SEED_TABLES = [
    ("T1", 2),
    ("T2", 2),
    ("T3", 2),
    ("T4", 4),
    ("T5", 4),
    ("T6", 4),
    ("T7", 6),
    ("T8", 6),
    ("Patio 1", 2),
    ("Patio 2", 4),
    ("Booth 1", 4),
    ("Booth 2", 8),
]


def upgrade() -> None:
    values = ", ".join(f"('{label}', {seats})" for label, seats in SEED_TABLES)
    op.execute(
        f"""
        INSERT INTO restaurant_tables (label, seats)
        SELECT v.label, v.seats
        FROM (VALUES {values}) AS v(label, seats)
        WHERE NOT EXISTS (
            SELECT 1 FROM restaurant_tables t WHERE t.label = v.label
        )
        """
    )


def downgrade() -> None:
    labels = ", ".join(f"'{label}'" for label, _ in SEED_TABLES)
    op.execute(
        f"""
        DELETE FROM restaurant_tables
        WHERE label IN ({labels})
          AND id NOT IN (SELECT DISTINCT table_id FROM reservations)
        """
    )
