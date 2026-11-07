# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Admin commands run inside the container, e.g.
    docker exec onesearch onesearch-admin reset-password alice
"""
import argparse
import logging
import os
import pwd
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .api.auth import hash_password
from .db.database import SessionLocal
from .models import User
from .services.audit import COMMAND_LINE_ACTOR, AuditAction, AuditTarget, record_event

logger = logging.getLogger(__name__)

# No 0/O/1/I/l so the password can be read off a terminal and typed back in
TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
TEMP_PASSWORD_LENGTH = 16


def generate_temporary_password() -> str:
    return "".join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(TEMP_PASSWORD_LENGTH))


def record_password_reset_event(db: Session, user: User) -> None:
    logger.info("Password reset from the command line for user: %s", user.username)
    record_event(
        db,
        actor=COMMAND_LINE_ACTOR,
        action=AuditAction.USER_PASSWORD_RESET,
        target=AuditTarget.user(user.id, user.username),
    )


def reset_password(db: Session, username: str) -> str | None:
    """Give the user a temporary password and end their sessions. None if no such user."""
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return None

    password = generate_temporary_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.session_version += 1
    record_password_reset_event(db, user)
    db.commit()
    return password


def drop_root(app_user: str = "onesearch") -> None:
    """docker exec runs as root, but the server runs as the app user. Writing the
    database as root can leave root-owned SQLite files the server can't open."""
    if os.geteuid() != 0:
        return
    try:
        account = pwd.getpwnam(app_user)
    except KeyError:
        return
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onesearch-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset-password", help="set a temporary password for a user")
    reset.add_argument("username")
    args = parser.parse_args(argv)

    drop_root()
    with SessionLocal() as db:
        password = reset_password(db, args.username)
        if password is None:
            names = db.execute(select(User.username).order_by(User.username)).scalars().all()
            print(
                f"No user named {args.username}. Users: {', '.join(names) or 'none'}",
                file=sys.stderr,
            )
            return 1

    print(f"Temporary password for {args.username}: {password}")
    print(f"{args.username} must change it at the next sign-in. Their old sessions have ended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
