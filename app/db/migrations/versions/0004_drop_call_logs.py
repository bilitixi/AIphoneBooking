"""drop call_logs

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10

Per-utterance transcripts are no longer persisted; they only go to the
application log. phone_calls (one row per call with its outcome) stays.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("call_logs")


def downgrade() -> None:
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
