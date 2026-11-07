# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import OperationalError

from app.api import auth as auth_module
from app.api.auth import ending_sessions_values
from app.models import ROLE_MEMBER, ApiToken, User
from app.services.agent_auth import hash_token


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


@pytest.fixture
def document_stub(monkeypatch):
    async def get_document(document_id):
        return {
            "id": document_id,
            "source_id": "photos",
            "source_name": "Photos",
            "path": "/photos/a.txt",
            "basename": "a.txt",
            "extension": "txt",
            "type": "text",
            "size_bytes": 3,
            "modified_at": 1,
            "indexed_at": 1,
            "content": "abc",
            "title": None,
            "metadata": {},
        }

    monkeypatch.setattr("app.api.search.meili_service.get_document", get_document)


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_token(client, name="laptop", expires_in_days=None):
    response = client.post("/api/auth/tokens", json={"name": name, "expires_in_days": expires_in_days})
    assert response.status_code == 201
    return response.json()


def _search(client, token: str):
    return client.post("/api/search", json={"q": "invoice"}, headers=_as(token))


def test_create_returns_secret_once_and_list_never_shows_it(client):
    created = _create_token(client)

    assert created["token"].startswith("os_")
    assert created["display_prefix"] == created["token"][:7]
    assert created["scope"] == "search"
    assert created["revoked"] is False
    assert created["expires_at"] is None
    assert created["last_used_at"] is None

    listed = client.get("/api/auth/tokens")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    row = listed.json()[0]
    assert "token" not in row
    assert created["token"] not in listed.text
    assert row["id"] == created["id"]
    assert row["name"] == "laptop"


def test_only_the_hash_is_stored(client, db_session):
    created = _create_token(client)

    row = db_session.query(ApiToken).one()
    assert row.token_hash == hash_token(created["token"])
    assert row.token_hash != created["token"]
    assert created["token"] not in {row.token_hash, row.display_prefix, row.name}


@pytest.mark.parametrize(
    ("days", "expected_days"),
    [(None, None), (30, 30), (90, 90), (365, 365)],
)
def test_expiry_is_never_or_a_fixed_number_of_days(client, days, expected_days):
    created = _create_token(client, expires_in_days=days)

    if expected_days is None:
        assert created["expires_at"] is None
        return
    expires_at = datetime.fromisoformat(created["expires_at"]).replace(tzinfo=None)
    now = datetime.now(UTC).replace(tzinfo=None)
    assert abs((expires_at - (now + timedelta(days=expected_days))).total_seconds()) < 60


@pytest.mark.parametrize("days", [1, 7, 60, 0])
def test_other_expiry_choices_are_rejected(client, days):
    response = client.post("/api/auth/tokens", json={"name": "x", "expires_in_days": days})

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_name_is_required_and_short(client, name):
    response = client.post("/api/auth/tokens", json={"name": name})

    assert response.status_code == 422


def test_name_is_trimmed(client):
    created = _create_token(client, name="  laptop  ")

    assert created["name"] == "laptop"


def test_token_searches_and_opens_documents(client, search_stub, document_stub):
    token = _create_token(client)["token"]

    assert _search(client, token).status_code == 200
    document = client.get("/api/documents/photos--abc", headers=_as(token))
    assert document.status_code == 200
    assert document.json()["id"] == "photos--abc"


def test_token_reaches_preview_and_download_link_routes(client, monkeypatch):
    async def missing_document(document_id):
        return None

    monkeypatch.setattr("app.api.preview.meili_service.get_document", missing_document)
    token = _create_token(client)["token"]

    preview = client.get("/api/documents/missing/preview", headers=_as(token))
    link = client.post("/api/documents/missing/download-link", headers=_as(token))

    assert preview.status_code == 404
    assert preview.json()["detail"]["code"] == "document_not_found"
    assert link.status_code == 404
    assert link.json()["detail"]["code"] == "document_not_found"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/me"),
        ("GET", "/api/auth/tokens"),
        ("POST", "/api/auth/tokens"),
        ("DELETE", "/api/auth/tokens/1"),
        ("POST", "/api/auth/change-password"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/users"),
        ("GET", "/api/sources"),
        ("GET", "/api/settings"),
    ],
)
def test_token_gets_403_outside_search(client, method, path):
    token = _create_token(client)["token"]

    response = client.request(method, path, headers=_as(token), json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "API tokens can only be used for search"


def test_token_cannot_make_another_token(client):
    token = _create_token(client)["token"]

    response = client.post("/api/auth/tokens", json={"name": "child"}, headers=_as(token))

    assert response.status_code == 403
    assert [row["name"] for row in client.get("/api/auth/tokens").json()] == ["laptop"]


def test_revoked_token_is_401_and_drops_off_the_list(client, search_stub):
    created = _create_token(client)
    assert _search(client, created["token"]).status_code == 200

    revoke = client.delete(f"/api/auth/tokens/{created['id']}")

    assert revoke.status_code == 204
    response = _search(client, created["token"])
    assert response.status_code == 401
    assert response.json()["detail"] == "API token revoked"
    rows = client.get("/api/auth/tokens").json()
    assert [(row["id"], row["status"], row["revoked"]) for row in rows] == [(created["id"], "revoked", True)]
    assert rows[0]["revoked_at"] is not None
    assert client.delete(f"/api/auth/tokens/{created['id']}").status_code == 404


def test_list_keeps_revoked_and_expired_tokens_newest_first(client, db_session):
    active = _create_token(client, name="backup-script")
    revoked = _create_token(client, name="old-laptop")
    expired = _create_token(client, name="ci-job", expires_in_days=30)
    assert client.delete(f"/api/auth/tokens/{revoked['id']}").status_code == 204
    db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == expired["id"])
        .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
    )
    db_session.commit()

    rows = client.get("/api/auth/tokens").json()

    assert [(row["name"], row["status"]) for row in rows] == [
        ("ci-job", "expired"),
        ("old-laptop", "revoked"),
        ("backup-script", "active"),
    ]
    assert rows[0]["revoked_at"] is None
    assert rows[0]["revoked"] is False
    assert rows[2]["id"] == active["id"]
    assert rows[2]["revoked_at"] is None


def test_revoked_and_expired_token_reports_revoked(client, db_session):
    created = _create_token(client, expires_in_days=30)
    assert client.delete(f"/api/auth/tokens/{created['id']}").status_code == 204
    db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == created["id"])
        .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
    )
    db_session.commit()

    assert client.get("/api/auth/tokens").json()[0]["status"] == "revoked"


def test_expired_token_is_401(client, db_session, search_stub):
    created = _create_token(client, expires_in_days=30)
    db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == created["id"])
        .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1))
    )
    db_session.commit()

    response = _search(client, created["token"])

    assert response.status_code == 401
    assert response.json()["detail"] == "API token expired"


def test_unknown_token_is_401(client, search_stub):
    response = _search(client, "os_not-a-real-token")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API token"


def test_user_cannot_revoke_someone_elses_token(client, member_client):
    member_token = _create_token(member_client, name="member laptop")

    response = client.delete(f"/api/auth/tokens/{member_token['id']}")

    assert response.status_code == 404
    assert [row["name"] for row in member_client.get("/api/auth/tokens").json()] == ["member laptop"]


def test_lists_only_your_own_tokens(client, member_client):
    _create_token(client, name="admin one")
    _create_token(member_client, name="member one")

    assert [row["name"] for row in client.get("/api/auth/tokens").json()] == ["admin one"]
    assert [row["name"] for row in member_client.get("/api/auth/tokens").json()] == ["member one"]


def test_disabled_owner_is_401(client, db_session, member_user, member_client, search_stub):
    token = _create_token(member_client)["token"]
    member_user.is_active = False
    db_session.commit()

    response = _search(client, token)

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found or inactive"


def test_owner_who_must_change_password_gets_403(client, db_session, search_stub):
    token = _create_token(client)["token"]
    user = db_session.query(User).filter_by(username="testuser").one()
    user.must_change_password = True
    db_session.commit()

    response = _search(client, token)

    assert response.status_code == 403
    assert response.json()["detail"] == "Password change required"


def test_demoted_owner_keeps_search(client, db_session, search_stub):
    token = _create_token(client)["token"]
    user = db_session.query(User).filter_by(username="testuser").one()
    user.role = ROLE_MEMBER
    db_session.commit()

    assert _search(client, token).status_code == 200
    assert user.role == ROLE_MEMBER


def test_password_change_does_not_revoke_tokens(client, search_stub):
    token = _create_token(client)["token"]

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": "testpass", "new_password": "testpass2"},
    )

    assert changed.status_code == 200
    assert _search(client, token).status_code == 200


def test_session_version_bump_does_not_revoke_tokens(client, db_session, search_stub):
    token = _create_token(client)["token"]
    db_session.execute(update(User).where(User.username == "testuser").values(**ending_sessions_values()))
    db_session.commit()

    assert _search(client, token).status_code == 200


def test_last_used_is_written_at_most_once_a_minute(client, db_session, search_stub):
    created = _create_token(client)
    token_row = db_session.get(ApiToken, created["id"])
    assert token_row.last_used_at is None

    assert _search(client, created["token"]).status_code == 200
    db_session.expire_all()
    first_use = db_session.get(ApiToken, created["id"]).last_used_at
    assert first_use is not None

    assert _search(client, created["token"]).status_code == 200
    db_session.expire_all()
    assert db_session.get(ApiToken, created["id"]).last_used_at == first_use

    db_session.execute(
        update(ApiToken)
        .where(ApiToken.id == created["id"])
        .values(last_used_at=first_use - timedelta(minutes=2))
    )
    db_session.commit()
    assert _search(client, created["token"]).status_code == 200
    db_session.expire_all()
    assert db_session.get(ApiToken, created["id"]).last_used_at > first_use - timedelta(minutes=1)


def test_deleting_a_user_deletes_their_tokens(client, db_session, member_user, member_client, search_stub):
    token = _create_token(member_client)["token"]
    assert db_session.query(ApiToken).filter_by(user_id=member_user.id).count() == 1

    response = client.delete(f"/api/users/{member_user.id}")

    assert response.status_code == 204
    assert db_session.query(ApiToken).filter_by(user_id=member_user.id).count() == 0
    assert _search(client, token).status_code == 401



def test_search_still_works_when_recording_last_used_hits_a_locked_database(
    client, db_engine, search_stub
):
    token = _create_token(client)["token"]

    def locked(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE API_TOKENS"):
            raise OperationalError(statement, parameters, sqlite3.OperationalError("database is locked"))

    event.listen(db_engine, "before_cursor_execute", locked)
    try:
        response = _search(client, token)
    finally:
        event.remove(db_engine, "before_cursor_execute", locked)

    assert response.status_code == 200
