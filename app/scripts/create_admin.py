"""CLI to create or update an admin_users row.

Usage:
    python -m app.scripts.create_admin <username>

Prompts for the password (not taken as an argv to avoid shell history/ps
leaking it). If the username already exists, updates its password instead
of creating a duplicate. Always creates with role=manager — this is the
bootstrap path for the first admin(s); managers create staff accounts
(and other managers) afterwards through POST /api/admin-users.
"""
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import AdminUser
from app.db.session import async_session_factory


async def create_admin(username: str, password: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(AdminUser).where(AdminUser.username == username))
        admin = result.scalar_one_or_none()

        if admin is None:
            admin = AdminUser(username=username, password_hash=hash_password(password), role="manager")
            db.add(admin)
            action = "Created"
        else:
            admin.password_hash = hash_password(password)
            admin.is_active = True
            action = "Updated"

        await db.commit()
        print(f"{action} admin user '{username}'")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m app.scripts.create_admin <username>", file=sys.stderr)
        sys.exit(1)

    username = sys.argv[1]
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match", file=sys.stderr)
        sys.exit(1)
    if not password:
        print("Password cannot be empty", file=sys.stderr)
        sys.exit(1)

    asyncio.run(create_admin(username, password))


if __name__ == "__main__":
    main()
