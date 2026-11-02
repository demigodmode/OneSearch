# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import re

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import update

from app.api import auth as auth_module
from app.api.access import AccessLevel, access_level_of
from app.main import app
from app.models import User

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
    gated = []
    for route in app.routes:
        if isinstance(route, APIRoute) and access_level_of(route) in (AccessLevel.SIGNED_IN, AccessLevel.ADMIN):
            for method in sorted(route.methods):
                if (method, route.path) not in PASSWORD_CHANGE_EXEMPT:
                    gated.append((method, route.path))
    return gated


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
