"""add role to admin_users

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-10

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("role", sa.Text, nullable=False, server_default="manager"),
    )
    op.create_check_constraint(
        "ck_admin_user_role", "admin_users", "role in ('manager', 'staff')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_admin_user_role", "admin_users", type_="check")
    op.drop_column("admin_users", "role")
