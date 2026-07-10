"""capacity-based booking: drop restaurant_tables, add capacity_limits

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10

Booking moves from per-table (exclusion constraint) to whole-restaurant
capacity: confirmed overlapping party sizes are summed and checked against
capacity_limits windows (default from settings when no window matches).
Concurrency is serialized with pg_advisory_xact_lock in the service layer.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_limits",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("max_customers", sa.Integer, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("max_customers >= 0", name="ck_capacity_limit_nonnegative"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_capacity_limit_time_order"),
    )
    op.create_index("idx_capacity_limits_time", "capacity_limits", ["starts_at", "ends_at"])

    op.execute("ALTER TABLE reservations DROP CONSTRAINT IF EXISTS excl_reservations_no_overlap")
    op.drop_index("idx_reservations_table_time", table_name="reservations")
    op.drop_column("reservations", "table_id")
    op.create_index("idx_reservations_time", "reservations", ["starts_at", "ends_at"])

    op.drop_table("restaurant_tables")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading would need restaurant_tables rows and per-reservation "
        "table assignments that no longer exist; restore from a backup instead."
    )
