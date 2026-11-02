# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.auth import hash_password, rate_limit_store
from app.db.database import get_db
from app.main import app
from app.models import ROLE_ADMIN, ROLE_MEMBER, User

BACKEND = Path(__file__).resolve().parents[1]
OLD_PASSWORD = "old-password-123"


@pytest.fixture(autouse=True)
def clear_rate_limit():
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "admin.db"
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{path.as_posix()}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        check=True,
    )
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        db.add_all([
            User(username="alice", password_hash=hash_password(OLD_PASSWORD), role=ROLE_MEMBER),
            User(username="root", password_hash=hash_password(OLD_PASSWORD), role=ROLE_ADMIN),
        ])
        db.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield path, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def run_admin(database_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
    return subprocess.run(
        [sys.executable, "-m", "app.admin_cli", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def login(client: TestClient, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def temporary_password_from(stdout: str, username: str) -> str:
    prefix = f"Temporary password for {username}: "
    line = next(line for line in stdout.splitlines() if line.startswith(prefix))
    return line[len(prefix):]


@pytest.mark.parametrize("username", ["alice", "root"])
def test_reset_password_issues_a_working_temporary_password_and_ends_old_sessions(database, username):
    database_path, session_factory = database
    client = TestClient(app)
    old_token = login(client, username, OLD_PASSWORD).json()["access_token"]

    result = run_admin(database_path, "reset-password", username)

    assert result.returncode == 0, result.stderr
    temporary = temporary_password_from(result.stdout, username)
    assert len(temporary) == 16
    assert "must change" in result.stdout

    headers = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert login(client, username, OLD_PASSWORD).status_code == 401

    signed_in = login(client, username, temporary)
    assert signed_in.status_code == 200
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    )
    assert me.json()["must_change_password"] is True
    assert me.json()["username"] == username

    with session_factory() as db:
        user = db.execute(select(User).where(User.username == username)).scalar_one()
        assert user.must_change_password is True


def test_reset_password_for_unknown_user_lists_the_usernames(database):
    database_path, _ = database

    result = run_admin(database_path, "reset-password", "nobody")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "No user named nobody. Users: alice, root"


def test_reset_password_for_unknown_user_leaves_accounts_alone(database):
    database_path, session_factory = database
    client = TestClient(app)

    run_admin(database_path, "reset-password", "nobody")

    assert login(client, "alice", OLD_PASSWORD).status_code == 200
    with session_factory() as db:
        assert db.execute(select(User).where(User.username == "alice")).scalar_one().must_change_password is False


def test_drops_to_the_app_user_when_run_as_root(monkeypatch):
    import types

    from app import admin_cli

    calls = []
    monkeypatch.setattr(admin_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        admin_cli.pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=1000, pw_gid=1001)
    )
    monkeypatch.setattr(admin_cli.os, "setgroups", lambda groups: calls.append(("groups", groups)))
    monkeypatch.setattr(admin_cli.os, "setgid", lambda gid: calls.append(("gid", gid)))
    monkeypatch.setattr(admin_cli.os, "setuid", lambda uid: calls.append(("uid", uid)))

    admin_cli.drop_root()

    assert calls == [("groups", []), ("gid", 1001), ("uid", 1000)]


def test_leaves_privileges_alone_when_not_root(monkeypatch):
    from app import admin_cli

    monkeypatch.setattr(admin_cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(admin_cli.os, "setuid", lambda uid: pytest.fail("setuid called"))

    admin_cli.drop_root()


def test_stays_root_when_there_is_no_app_user(monkeypatch):
    from app import admin_cli

    monkeypatch.setattr(admin_cli.os, "geteuid", lambda: 0)

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(admin_cli.pwd, "getpwnam", missing)
    monkeypatch.setattr(admin_cli.os, "setuid", lambda uid: pytest.fail("setuid called"))

    admin_cli.drop_root()
