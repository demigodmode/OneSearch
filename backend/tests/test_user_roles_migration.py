# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_user_roles_migration_makes_existing_users_admins_and_downgrades(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade.db"
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{database.as_posix()}"}

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
            cwd=backend,
            env=environment,
            check=True,
        )

    alembic("upgrade", "f9c23a14b980")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, is_active, created_at, updated_at) "
            "VALUES ('legacy', 'hash', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    alembic("upgrade", "head")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT role, session_version, must_change_password, last_login_at, created_by_id "
            "FROM users WHERE username='legacy'"
        ).fetchone()
    assert row == ("admin", 0, 0, None, None)

    alembic("downgrade", "-1")
    with sqlite3.connect(database) as connection:
        columns = {info[1] for info in connection.execute("PRAGMA table_info(users)")}
    assert not {"role", "session_version", "must_change_password", "created_by_id", "last_login_at"} & columns
    assert "username" in columns
