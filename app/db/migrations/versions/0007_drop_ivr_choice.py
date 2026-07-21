"""drop ivr_choice from phone_calls

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("phone_calls", "ivr_choice")


def downgrade() -> None:
    op.add_column("phone_calls", sa.Column("ivr_choice", sa.Text))
