"""Operator commands.

    python -m app.cli create-admin admin@example.com --name "Ops Admin"
    python -m app.cli promote user@example.com

The password is read from the ADMIN_PASSWORD environment variable or prompted for;
it is never accepted on the command line (it would end up in shell history).
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.core.security import hash_password
from app.db.database import dispose_engine, get_sessionmaker
from app.db.models import Role
from app.db.repositories.user_repository import UserRepository
from app.services import audit_service


async def _create_admin(email: str, name: str) -> int:
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    if len(password) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        return 1
    async with get_sessionmaker()() as session:
        users = UserRepository(session)
        if await users.get_by_email(email):
            print("A user with that email already exists; use `promote`.", file=sys.stderr)
            return 1
        user = await users.create(email, hash_password(password), name)
        user.role = Role.ADMIN
        await audit_service.record(session, "admin.create", user_id=user.id, actor="system")
        await session.commit()
    print(f"Admin {email} created.")
    return 0


async def _promote(email: str) -> int:
    async with get_sessionmaker()() as session:
        user = await UserRepository(session).get_by_email(email)
        if user is None:
            print("No such user.", file=sys.stderr)
            return 1
        user.role = Role.ADMIN
        user.token_version += 1  # re-issue tokens with the new role
        await audit_service.record(session, "admin.promote", user_id=user.id, actor="system")
        await session.commit()
    print(f"{email} is now an admin.")
    return 0


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="create an administrator account")
    create.add_argument("email")
    create.add_argument("--name", default="Administrator")
    promote = sub.add_parser("promote", help="make an existing user an administrator")
    promote.add_argument("email")
    args = parser.parse_args(argv)
    try:
        if args.command == "create-admin":
            return await _create_admin(args.email, args.name)
        return await _promote(args.email)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
