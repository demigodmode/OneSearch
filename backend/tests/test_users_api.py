# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.api import auth as auth_module
from app.api.access import AccessLevel
from app.api.auth import create_access_token, hash_password
from app.api.users import _active_admins_lock_statement
from app.db.database import get_db
from app.main import app
from app.models import ROLE_ADMIN, AgentEnrollment, Base, User

from .route_helpers import routes_at

PASSWORD_CHANGE_EXEMPT = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/change-password"),
}


@pytest.fixture(autouse=True)
def clear_rate_limit():
    auth_module.rate_limit_store.clear()
    yield
    auth_module.rate_limit_store.clear()


@pytest.fixture
def search_stub(monkeypatch):
    async def search(**_kwargs):
        return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 1}

    monkeypatch.setattr("app.api.search.meili_service.search", search)


def _create_user(client, username="alice", password="alicepass1", role="member"):
    return client.post("/api/users", json={"username": username, "password": password, "role": role})


def _sign_in(client, username="alice", password="alicepass1"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _as(token):
    return {"Authorization": f"Bearer {token}"}


def _change_password(client, token, current, new):
    return client.post(
        "/api/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=_as(token),
    )


def _gated_routes():
    return [
        route
        for route in routes_at(AccessLevel.SIGNED_IN, AccessLevel.SEARCH, AccessLevel.ADMIN)
        if route not in PASSWORD_CHANGE_EXEMPT
    ]


def _fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "dummy", path)


def test_admin_creates_member_with_temporary_password(client):
    response = _create_user(client)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["role"] == "member"
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert body["created_by"] == "testuser"
    assert body["last_login_at"] is None
    assert isinstance(body["created_at"], str)


def test_new_member_is_stopped_until_password_changed(client, search_stub):
    _create_user(client)
    token = _sign_in(client)

    search = client.post("/api/search", json={"q": "invoice"}, headers=_as(token))
    assert search.status_code == 403
    assert search.json()["detail"] == "Password change required"

    me = client.get("/api/auth/me", headers=_as(token))
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    logout = client.post("/api/auth/logout", headers=_as(token))
    assert logout.status_code == 200


def test_member_changes_password_and_old_session_ends(client, search_stub):
    _create_user(client)
    old_token = _sign_in(client)

    response = _change_password(client, old_token, "alicepass1", "alicepass2")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    new_token = body["access_token"]

    old_session = client.get("/api/auth/me", headers=_as(old_token))
    assert old_session.status_code == 401
    assert old_session.json()["detail"] == "Session expired"

    me = client.get("/api/auth/me", headers=_as(new_token))
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False

    search = client.post("/api/search", json={"q": "invoice"}, headers=_as(new_token))
    assert search.status_code == 200

    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepass1"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepass2"}).status_code == 200


def test_wrong_current_password_is_rejected(client):
    _create_user(client)
    token = _sign_in(client)

    response = _change_password(client, token, "not-the-password", "alicepass2")

    assert response.status_code == 400
    assert response.json() == {"detail": "Current password is incorrect"}
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepass1"}).status_code == 200


def test_new_password_must_differ_from_current(client):
    _create_user(client)
    token = _sign_in(client)

    response = _change_password(client, token, "alicepass1", "alicepass1")

    assert response.status_code == 400
    assert response.json()["detail"] == "New password must be different from the current password"


def test_new_password_must_be_at_least_eight_characters(client):
    _create_user(client)
    token = _sign_in(client)

    response = _change_password(client, token, "alicepass1", "short")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": "alicepass1", "role": "member"},
        {"username": "x" * 51, "password": "alicepass1", "role": "member"},
        {"username": "alice", "password": "short", "role": "member"},
        {"username": "alice", "password": "alicepass1", "role": "owner"},
    ],
)
def test_create_user_validates_input(client, payload):
    response = client.post("/api/users", json=payload)

    assert response.status_code == 422


def test_duplicate_username_is_rejected(client):
    assert _create_user(client).status_code == 201

    duplicate = _create_user(client)
    taken_by_admin = _create_user(client, username="testuser")

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Username already exists"}
    assert taken_by_admin.status_code == 409


def test_list_shows_creator_and_last_login(client):
    _create_user(client)

    before = client.get("/api/users")
    assert before.status_code == 200
    rows = {row["username"]: row for row in before.json()}
    assert [row["username"] for row in before.json()] == ["alice", "testuser"]
    assert rows["alice"]["created_by"] == "testuser"
    assert rows["alice"]["last_login_at"] is None
    assert rows["testuser"]["created_by"] is None

    _sign_in(client)

    after = {row["username"]: row for row in client.get("/api/users").json()}
    assert isinstance(after["alice"]["last_login_at"], str)


def test_must_change_user_is_blocked_from_every_gated_route(client):
    _create_user(client)
    token = _sign_in(client)

    gated = _gated_routes()
    assert len(gated) > 10

    for method, path in gated:
        response = client.request(method, _fill_path(path), headers=_as(token))
        assert response.status_code == 403, f"{method} {path}"
        assert response.json()["detail"] == "Password change required", f"{method} {path}"


def test_wrong_current_password_attempts_are_rate_limited(client):
    _create_user(client)
    token = _sign_in(client)

    for _ in range(5):
        assert _change_password(client, token, "not-the-password", "alicepass2").status_code == 400

    response = _change_password(client, token, "not-the-password", "alicepass2")
    assert response.status_code == 429


def test_password_change_limit_does_not_lock_out_other_users(client, test_user):
    _create_user(client)
    alice_token = _sign_in(client)
    for _ in range(6):
        _change_password(client, alice_token, "not-the-password", "alicepass2")

    admin_attempt = _change_password(client, test_user["token"], "not-the-password", "adminpass2")

    assert admin_attempt.status_code == 400


def test_password_change_fails_when_session_version_moves_mid_request(client, db_session, monkeypatch):
    _create_user(client)
    token = _sign_in(client)
    real_hash_password = auth_module.hash_password

    def bump_then_hash(password):
        db_session.execute(
            update(User).where(User.username == "alice").values(session_version=User.session_version + 1)
        )
        db_session.commit()
        return real_hash_password(password)

    monkeypatch.setattr(auth_module, "hash_password", bump_then_hash)
    response = _change_password(client, token, "alicepass1", "alicepass2")
    monkeypatch.undo()

    assert response.status_code == 409
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepass1"}).status_code == 200


def _admin_user_id(client, username="alice"):
    return next(row["id"] for row in client.get("/api/users").json() if row["username"] == username)


def test_admin_disables_and_enables_a_member(client):
    _create_user(client)
    alice_id = _admin_user_id(client)
    _sign_in(client)

    disabled = client.patch(f"/api/users/{alice_id}", json={"is_active": False})

    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert disabled.json()["username"] == "alice"
    assert disabled.json()["created_by"] == "testuser"
    assert {row["username"]: row["is_active"] for row in client.get("/api/users").json()}["alice"] is False

    refused = client.post("/api/auth/login", json={"username": "alice", "password": "alicepass1"})
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Account is disabled"

    enabled = client.patch(f"/api/users/{alice_id}", json={"is_active": True})
    assert enabled.json()["is_active"] is True
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepass1"}).status_code == 200


def test_disabled_user_session_gets_401_and_stays_dead_after_enable(client):
    _create_user(client)
    alice_id = _admin_user_id(client)
    token = _sign_in(client)

    client.patch(f"/api/users/{alice_id}", json={"is_active": False})
    assert client.get("/api/auth/me", headers=_as(token)).status_code == 401

    client.patch(f"/api/users/{alice_id}", json={"is_active": True})
    response = client.get("/api/auth/me", headers=_as(token))
    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired"


def test_role_change_ends_existing_sessions(client):
    _create_user(client)
    alice_id = _admin_user_id(client)
    first = _sign_in(client)
    member_token = _change_password(client, first, "alicepass1", "alicepass2").json()["access_token"]

    response = client.patch(f"/api/users/{alice_id}", json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert client.get("/api/auth/me", headers=_as(member_token)).status_code == 401
    new_token = _sign_in(client, password="alicepass2")
    assert client.get("/api/users", headers=_as(new_token)).status_code == 200


def test_same_role_keeps_sessions(client):
    _create_user(client)
    alice_id = _admin_user_id(client)
    token = _sign_in(client)

    assert client.patch(f"/api/users/{alice_id}", json={"role": "member"}).status_code == 200

    assert client.get("/api/auth/me", headers=_as(token)).status_code == 200


def test_reset_password_ends_old_session_and_forces_a_change(client, search_stub):
    _create_user(client)
    alice_id = _admin_user_id(client)
    old_token = _sign_in(client)
    _change_password(client, old_token, "alicepass1", "alicepass2")
    old_token = _sign_in(client, password="alicepass2")

    response = client.post(f"/api/users/{alice_id}/reset-password", json={"password": "tempreset1"})

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert client.get("/api/auth/me", headers=_as(old_token)).status_code == 401

    old_password = client.post("/api/auth/login", json={"username": "alice", "password": "alicepass2"})
    assert old_password.status_code == 401

    new_token = _sign_in(client, password="tempreset1")
    blocked = client.post("/api/search", json={"q": "invoice"}, headers=_as(new_token))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required"

    _change_password(client, new_token, "tempreset1", "alicepass3")
    fresh = _sign_in(client, password="alicepass3")
    assert client.post("/api/search", json={"q": "invoice"}, headers=_as(fresh)).status_code == 200


def test_reset_password_rejects_short_password(client):
    _create_user(client)
    alice_id = _admin_user_id(client)

    response = client.post(f"/api/users/{alice_id}/reset-password", json={"password": "short"})

    assert response.status_code == 422


def test_delete_user_clears_who_created_others(client):
    assert _create_user(client, username="carol", password="carolpass1", role="admin").status_code == 201
    carol_token = _sign_in(client, username="carol", password="carolpass1")
    _change_password(client, carol_token, "carolpass1", "carolpass2")
    carol_token = _sign_in(client, username="carol", password="carolpass2")
    dave = client.post(
        "/api/users",
        json={"username": "dave", "password": "davepass1", "role": "member"},
        headers=_as(carol_token),
    )
    assert dave.json()["created_by"] == "carol"
    carol_id = _admin_user_id(client, "carol")

    response = client.delete(f"/api/users/{carol_id}")

    assert response.status_code == 204
    rows = {row["username"]: row for row in client.get("/api/users").json()}
    assert "carol" not in rows
    assert rows["dave"]["created_by"] is None


def test_deleting_a_user_removes_their_enrollment_codes(client, db_session):
    _create_user(client)
    alice_id = _admin_user_id(client)
    db_session.add(
        AgentEnrollment(
            id="alice-code",
            code_hash="a" * 64,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15),
            created_by_user_id=alice_id,
        )
    )
    db_session.commit()

    response = client.delete(f"/api/users/{alice_id}")

    assert response.status_code == 204
    assert db_session.get(AgentEnrollment, "alice-code") is None
    assert db_session.get(User, alice_id) is None


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "", {"is_active": False}),
        ("PATCH", "", {"role": "member"}),
        ("DELETE", "", None),
    ],
)
def test_admin_cannot_disable_demote_or_delete_themselves(client, db_session, method, suffix, body):
    me_id = _admin_user_id(client, "testuser")

    response = client.request(method, f"/api/users/{me_id}{suffix}", json=body)

    assert response.status_code == 400
    assert response.json() == {"detail": "You can't do that to your own account"}
    assert db_session.get(User, me_id).is_active is True
    assert db_session.get(User, me_id).role == "admin"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/users/{id}", {"is_active": False}),
        ("PATCH", "/api/users/{id}", {"role": "member"}),
        ("DELETE", "/api/users/{id}", None),
    ],
)
def test_last_active_admin_is_protected_from_demotion_disable_and_delete(client, db_session, monkeypatch, method, path, body):
    # The acting admin is always an active admin, so this only fires when another
    # admin is removed between the check and the write. Simulate that by reporting none left.
    assert _create_user(client, username="carol", password="carolpass1", role="admin").status_code == 201
    carol_id = _admin_user_id(client, "carol")
    monkeypatch.setattr("app.api.users._active_admin_ids_locked", lambda db: [carol_id])

    response = client.request(method, path.format(id=carol_id), json=body)

    assert response.status_code == 409
    assert response.json() == {"detail": "There has to be at least one active admin"}
    assert db_session.get(User, carol_id).role == "admin"
    assert db_session.get(User, carol_id).is_active is True


@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("PATCH", {"is_active": False}),
        ("POST", {"password": "tempreset1"}),
        ("DELETE", None),
    ],
)
def test_unknown_user_is_404(client, method, body):
    path = "/api/users/999/reset-password" if method == "POST" else "/api/users/999"

    response = client.request(method, path, json=body)

    assert response.status_code == 404


def test_disabled_admin_can_be_demoted_because_they_are_not_active(client):
    _create_user(client, username="carol", password="carolpass1", role="admin")
    carol_id = _admin_user_id(client, "carol")

    assert client.patch(f"/api/users/{carol_id}", json={"is_active": False}).status_code == 200
    assert client.patch(f"/api/users/{carol_id}", json={"role": "member"}).status_code == 200


@pytest.fixture
def file_client(tmp_path):
    # Real file so a second connection can hold SQLite's write lock.
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as session:
        admin = User(username="testuser", password_hash=hash_password("testpass"), is_active=True, role=ROLE_ADMIN)
        carol = User(username="carol", password_hash=hash_password("carolpass1"), is_active=True, role=ROLE_ADMIN)
        session.add_all([admin, carol])
        session.commit()
        token, _ = create_access_token(admin.id, admin.username, admin.session_version)
        carol_id = carol.id

    def override_get_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.headers.update({"Authorization": f"Bearer {token}"})
            yield client, engine, carol_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_check_runs_after_the_write_lock(file_client):
    client, engine, carol_id = file_client
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.patch(f"/api/users/{carol_id}", json={"role": "member"})
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    lock = statements.index("BEGIN IMMEDIATE")
    admin_check = next(i for i, s in enumerate(statements) if " ".join(s.split()).startswith("SELECT users.id FROM users WHERE users.role"))
    assert lock < admin_check


def test_admin_change_gives_409_while_another_writer_holds_the_lock(file_client):
    client, engine, carol_id = file_client
    blocker = engine.connect()
    try:
        blocker.exec_driver_sql("BEGIN IMMEDIATE")
        response = client.patch(f"/api/users/{carol_id}", json={"role": "member"})
    finally:
        blocker.rollback()
        blocker.close()

    assert response.status_code == 409
    assert response.json() == {"detail": "Someone else is changing users right now. Try again."}
    with engine.connect() as conn:
        assert conn.exec_driver_sql(f"SELECT role FROM users WHERE id={carol_id}").scalar() == ROLE_ADMIN


def test_admin_lock_query_takes_row_locks_on_postgresql():
    sql = str(_active_admins_lock_statement().compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql and "ORDER BY users.id" in sql
