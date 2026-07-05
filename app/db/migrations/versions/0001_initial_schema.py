"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "customers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("phone_number", sa.Text, nullable=False, unique=True),
        sa.Column("full_name", sa.Text),
        sa.Column("email", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "restaurant_tables",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("seats", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("seats > 0", name="ck_table_seats_positive"),
    )

    op.create_table(
        "reservations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", pg.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", pg.UUID(as_uuid=True), sa.ForeignKey("restaurant_tables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="confirmed"),
        sa.Column("source", sa.Text, nullable=False, server_default="ai_call"),
        sa.Column("special_requests", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_reservation_time_order"),
        sa.CheckConstraint(
            "status in ('confirmed','cancelled','completed','no_show')", name="ck_reservation_status"
        ),
        sa.CheckConstraint(
            "source in ('ai_call','staff_portal','takeaway_transfer')", name="ck_reservation_source"
        ),
    )
    op.create_index("idx_reservations_customer", "reservations", ["customer_id"])
    op.create_index("idx_reservations_table_time", "reservations", ["table_id", "starts_at"])

    # Prevents overlapping confirmed reservations on the same table — enforced
    # by Postgres itself so it holds even across multiple app workers.
    op.execute(
        """
        ALTER TABLE reservations
        ADD CONSTRAINT excl_reservations_no_overlap
        EXCLUDE USING gist (
            table_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
        ) WHERE (status = 'confirmed')
        """
    )

    op.create_table(
        "phone_calls",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("call_sid", sa.Text, nullable=False, unique=True),
        sa.Column("from_number", sa.Text, nullable=False),
        sa.Column("ivr_choice", sa.Text),
        sa.Column(
            "outcome",
            sa.Text,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "outcome in ('transferred_to_staff','handled_by_ai','escalated_to_staff','abandoned')",
            name="ck_phone_calls_outcome",
        ),
    )

    op.create_table(
        "call_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("call_id", pg.UUID(as_uuid=True), sa.ForeignKey("phone_calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_name", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role in ('caller','agent','tool')", name="ck_call_logs_role"),
    )
    op.create_index("idx_call_logs_call", "call_logs", ["call_id", "created_at"])


def downgrade() -> None:
    op.drop_table("call_logs")
    op.drop_table("phone_calls")
    op.drop_index("idx_reservations_table_time", table_name="reservations")
    op.drop_index("idx_reservations_customer", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("restaurant_tables")
    op.drop_table("customers")
