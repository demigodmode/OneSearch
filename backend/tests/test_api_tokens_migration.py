# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_api_tokens_migration_upgrades_and_downgrades(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "tokens.db"
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{database.as_posix()}"}

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
            cwd=backend,
            env=environment,
            check=True,
        )

    def table_columns():
        with sqlite3.connect(database) as connection:
            return {info[1]: info for info in connection.execute("PRAGMA table_info(api_tokens)")}

    alembic("upgrade", "5b9e0c3d7f16")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, is_active, role, created_at, updated_at) "
            "VALUES ('legacy', 'hash', 1, 'admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    alembic("upgrade", "head")
    alembic("check")
    columns = table_columns()
    assert set(columns) == {
        "id",
        "user_id",
        "name",
        "scope",
        "token_hash",
        "display_prefix",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
    }
    assert columns["user_id"][3] == 1  # NOT NULL
    assert columns["expires_at"][3] == 0
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        user_id = connection.execute("SELECT id FROM users WHERE username='legacy'").fetchone()[0]
        connection.execute(
            "INSERT INTO api_tokens (user_id, name, token_hash, display_prefix, created_at) "
            "VALUES (?, 'laptop', 'hash-1', 'os_AbCd', CURRENT_TIMESTAMP)",
            (user_id,),
        )
        connection.commit()
        scope = connection.execute("SELECT scope FROM api_tokens").fetchone()[0]
        assert scope == "search"
        connection.execute("DELETE FROM users WHERE id=?", (user_id,))
        remaining = connection.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0]
    assert remaining == 0

    alembic("downgrade", "-1")
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "api_tokens" not in tables
    assert "users" in tables

    alembic("upgrade", "head")
    assert "token_hash" in table_columns()
