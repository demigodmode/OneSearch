# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_audit_events_migration_upgrades_and_downgrades(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "audit.db"
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{database.as_posix()}"}

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
            cwd=backend,
            env=environment,
            check=True,
        )

    def tables():
        with sqlite3.connect(database) as connection:
            return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    alembic("upgrade", "c4e8a2d17b93")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, is_active, role, created_at, updated_at) "
            "VALUES ('legacy', 'hash', 1, 'admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        columns = {info[1]: info for info in connection.execute("PRAGMA table_info(audit_events)")}
        assert set(columns) == {
            "id",
            "created_at",
            "actor_user_id",
            "actor_username",
            "action",
            "target_type",
            "target_id",
            "target_label",
            "detail",
            "ip",
        }
        assert columns["created_at"][3] == 1  # NOT NULL
        assert columns["action"][3] == 1
        assert columns["actor_user_id"][3] == 0
        index_names = {row[1] for row in connection.execute("PRAGMA index_list('audit_events')")}
        assert {"ix_audit_events_created_at", "ix_audit_events_action"} <= index_names

        user_id = connection.execute("SELECT id FROM users WHERE username='legacy'").fetchone()[0]
        connection.execute(
            "INSERT INTO audit_events (created_at, actor_user_id, actor_username, action) "
            "VALUES (CURRENT_TIMESTAMP, ?, 'legacy', 'auth.login')",
            (user_id,),
        )
        connection.commit()
        connection.execute("DELETE FROM users WHERE id=?", (user_id,))
        connection.commit()
        row = connection.execute(
            "SELECT actor_user_id, actor_username FROM audit_events WHERE action='auth.login'"
        ).fetchone()
    assert row == (None, "legacy")

    alembic("downgrade", "c4e8a2d17b93")
    assert "audit_events" not in tables()
    assert "api_tokens" in tables()
    assert "users" in tables()

    alembic("upgrade", "head")
    assert "audit_events" in tables()
