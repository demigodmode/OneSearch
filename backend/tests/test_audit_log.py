# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.db.database import get_db
from app.main import app
from app.models import AuditEvent, User
from app.services import audit

TEMPORARY = "temporary-pass-1"
FORWARDED = {"X-Forwarded-For": "203.0.113.7"}


@pytest.fixture(autouse=True)
def clear_rate_limit():
    auth_module.rate_limit_store.clear()
    yield
    auth_module.rate_limit_store.clear()


@pytest.fixture
def signed_out(db_session):
    """Anonymous client on the same session as `client`, for the public routes."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as anonymous:
        yield anonymous
    app.dependency_overrides.clear()


def _as(token):
    return {"Authorization": f"Bearer {token}"}


def _sign_in(username, password, headers=None):
    response = TestClient(app).post(
        "/api/auth/login", json={"username": username, "password": password}, headers=headers or {}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _events(client, **params):
    response = client.get("/api/audit", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _latest(client, action, **params):
    matches = [event for event in _events(client, **params)["events"] if event["action"] == action]
    assert matches, f"no {action} entry"
    return matches[0]


def _create_member(client, username="alice", password=TEMPORARY):
    response = client.post(
        "/api/users", json={"username": username, "password": password, "role": "member"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_creates_user_is_logged(client):
    created = _create_member(client)

    event = _latest(client, "user.created")

    assert event["actor_username"] == "testuser"
    assert event["actor_user_id"] is not None
    assert event["target_type"] == "user"
    assert event["target_id"] == created["id"]
    assert event["target_label"] == "alice"
    assert event["detail"] == {"role": "member"}


def test_role_change_records_old_and_new_role(client):
    created = _create_member(client)

    response = client.patch(f"/api/users/{created['id']}", json={"role": "admin"})

    assert response.status_code == 200
    event = _latest(client, "user.role_changed")
    assert event["actor_username"] == "testuser"
    assert event["target_label"] == "alice"
    assert event["target_id"] == created["id"]
    assert event["detail"] == {"old": "member", "new": "admin"}


def test_disable_and_enable_are_logged_separately(client):
    created = _create_member(client)

    client.patch(f"/api/users/{created['id']}", json={"is_active": False})
    assert _latest(client, "user.disabled")["target_label"] == "alice"

    client.patch(f"/api/users/{created['id']}", json={"is_active": True})
    assert _latest(client, "user.enabled")["actor_username"] == "testuser"


def test_admin_reset_is_logged(client):
    created = _create_member(client)

    response = client.post(
        f"/api/users/{created['id']}/reset-password", json={"password": "another-temp-1"}
    )

    assert response.status_code == 200
    event = _latest(client, "user.password_reset")
    assert event["actor_username"] == "testuser"
    assert event["target_label"] == "alice"


def test_delete_is_logged(client):
    created = _create_member(client)

    assert client.delete(f"/api/users/{created['id']}").status_code == 204

    event = _latest(client, "user.deleted")
    assert event["target_label"] == "alice"
    assert event["actor_username"] == "testuser"


def test_user_changing_own_password_is_logged_as_them(client):
    created = _create_member(client)
    member = _sign_in("alice", TEMPORARY)

    response = TestClient(app).post(
        "/api/auth/change-password",
        json={"current_password": TEMPORARY, "new_password": "alice-new-pass"},
        headers=_as(member),
    )

    assert response.status_code == 200, response.text
    event = _latest(client, "user.password_changed")
    assert event["actor_username"] == "alice"
    assert event["actor_user_id"] == created["id"]
    assert event["target_label"] == "alice"


def test_successful_sign_in_is_logged_with_ip(client):
    created = _create_member(client)

    _sign_in("alice", TEMPORARY, headers=FORWARDED)

    event = _latest(client, "auth.login")
    assert event["actor_username"] == "alice"
    assert event["actor_user_id"] == created["id"]
    assert event["ip"] == "203.0.113.7"


def test_failed_sign_in_for_a_known_user(client, signed_out):
    created = _create_member(client)

    response = signed_out.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong-password"}, headers=FORWARDED
    )

    assert response.status_code == 401
    event = _latest(client, "auth.login_failed")
    assert event["actor_user_id"] is None
    assert event["actor_username"] is None
    assert event["target_id"] == created["id"]
    assert event["target_label"] == "alice"
    assert event["ip"] == "203.0.113.7"


def test_failed_sign_in_for_an_unknown_user_keeps_the_name(client, signed_out):
    response = signed_out.post(
        "/api/auth/login", json={"username": "ghost", "password": "whatever"}, headers=FORWARDED
    )

    assert response.status_code == 401
    event = _latest(client, "auth.login_failed")
    assert event["target_id"] is None
    assert event["target_label"] == "ghost"
    assert event["ip"] == "203.0.113.7"


def test_failed_sign_in_truncates_a_long_name(client, signed_out):
    signed_out.post("/api/auth/login", json={"username": "x" * 200, "password": "whatever"})

    assert _latest(client, "auth.login_failed")["target_label"] == "x" * 50


def test_sign_in_to_a_disabled_account_is_a_failed_sign_in(client, signed_out):
    created = _create_member(client)
    client.patch(f"/api/users/{created['id']}", json={"is_active": False})

    response = signed_out.post("/api/auth/login", json={"username": "alice", "password": TEMPORARY})

    assert response.status_code == 401
    event = _latest(client, "auth.login_failed")
    assert event["target_label"] == "alice"
    assert event["detail"] == {"reason": "account disabled"}


def test_setup_is_logged(db_session, signed_out):
    response = signed_out.post("/api/auth/setup", json={"username": "owner", "password": "longenough"})

    assert response.status_code == 200
    event = db_session.query(AuditEvent).filter_by(action="setup.completed").one()
    owner = db_session.query(User).filter_by(username="owner").one()
    assert event.actor_user_id == owner.id
    assert event.actor_username == "owner"
    assert event.target_label == "owner"


def test_entries_keep_the_name_after_the_person_is_deleted(client):
    created = _create_member(client, username="carol")
    client.patch(f"/api/users/{created['id']}", json={"role": "admin"})
    _sign_in("carol", TEMPORARY)

    assert client.delete(f"/api/users/{created['id']}").status_code == 204

    assert _latest(client, "auth.login", user="carol")["actor_username"] == "carol"
    assert _latest(client, "user.role_changed", user="carol")["target_label"] == "carol"


def test_filter_by_user_matches_actor_or_target(client, signed_out):
    _create_member(client)
    signed_out.post("/api/auth/login", json={"username": "alice", "password": "nope"})

    actions = {event["action"] for event in _events(client, user="alice")["events"]}

    assert actions == {"user.created", "auth.login_failed"}


def test_filter_by_exact_action(client, signed_out):
    _create_member(client)
    signed_out.post("/api/auth/login", json={"username": "alice", "password": "nope"})

    events = _events(client, action="auth.login_failed")["events"]

    assert [event["action"] for event in events] == ["auth.login_failed"]


def test_filter_by_action_prefix(client, signed_out):
    created = _create_member(client)
    client.patch(f"/api/users/{created['id']}", json={"is_active": False})
    signed_out.post("/api/auth/login", json={"username": "alice", "password": "nope"})

    actions = {event["action"] for event in _events(client, action="user.")["events"]}

    assert actions == {"user.created", "user.disabled"}


def test_action_without_a_dot_is_matched_exactly(client):
    _create_member(client)

    assert _events(client, action="auth.login_")["events"] == []


def test_paging_is_newest_first_with_a_cursor(client):
    for index in range(5):
        _create_member(client, username=f"user{index}")

    first = _events(client, action="user.created", limit=2)
    second = _events(client, action="user.created", limit=2, before=first["next_before"])
    last = _events(client, action="user.created", limit=2, before=second["next_before"])

    labels = [event["target_label"] for event in first["events"] + second["events"] + last["events"]]
    assert labels == ["user4", "user3", "user2", "user1", "user0"]
    assert first["next_before"] is not None
    assert second["next_before"] is not None
    assert last["next_before"] is None


def test_page_without_more_entries_has_no_cursor(client):
    _create_member(client)

    assert _events(client)["next_before"] is None


def test_limit_is_capped_at_200(client):
    assert client.get("/api/audit", params={"limit": 201}).status_code == 422


def test_member_gets_403(member_client):
    response = member_client.get("/api/audit")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_recording_failure_does_not_break_sign_in(client, signed_out, monkeypatch):
    _create_member(client)

    def broken(db, **fields):
        raise RuntimeError("audit table is gone")

    monkeypatch.setattr(audit, "_queue_entry", broken)

    assert signed_out.post(
        "/api/auth/login", json={"username": "alice", "password": TEMPORARY}
    ).status_code == 200
    assert signed_out.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    ).status_code == 401


def test_recording_failure_does_not_break_user_changes(client, monkeypatch):
    def broken(db, **fields):
        raise RuntimeError("audit table is gone")

    monkeypatch.setattr(audit, "_queue_entry", broken)

    created = _create_member(client)
    assert client.patch(f"/api/users/{created['id']}", json={"role": "admin"}).status_code == 200
    assert client.post(
        f"/api/users/{created['id']}/reset-password", json={"password": "another-temp-1"}
    ).status_code == 200
    assert client.patch(f"/api/users/{created['id']}", json={"is_active": False}).status_code == 200
    assert client.delete(f"/api/users/{created['id']}").status_code == 204

    monkeypatch.undo()
    assert _events(client)["events"] == []


def test_recording_failure_does_not_break_a_password_change(client, monkeypatch):
    _create_member(client)
    member = _sign_in("alice", TEMPORARY)

    def broken(db, **fields):
        raise RuntimeError("audit table is gone")

    monkeypatch.setattr(audit, "_queue_entry", broken)

    response = TestClient(app).post(
        "/api/auth/change-password",
        json={"current_password": TEMPORARY, "new_password": "alice-new-pass"},
        headers=_as(member),
    )

    assert response.status_code == 200, response.text
    monkeypatch.undo()
    _sign_in("alice", "alice-new-pass")


def test_no_entry_when_nothing_changes(client, monkeypatch):
    created = _create_member(client)
    calls = []
    monkeypatch.setattr(audit, "_queue_entry", lambda db, **fields: calls.append(fields))

    response = client.patch(f"/api/users/{created['id']}", json={"role": "member", "is_active": True})

    assert response.status_code == 200
    assert calls == []


def test_action_names_are_the_stored_strings():
    assert {action.value for action in audit.AuditAction} == {
        "auth.login",
        "auth.login_failed",
        "user.created",
        "user.role_changed",
        "user.password_reset",
        "user.password_changed",
        "user.disabled",
        "user.enabled",
        "user.deleted",
        "setup.completed",
    }


def test_free_text_is_clamped_to_the_column_sizes(db_session):
    audit.record_event(
        db_session,
        actor="x" * 500,
        action="a" * 100,
        target=audit.AuditTarget(type="t" * 100, id=None, label="y" * 500),
        ip="1" * 500,
    )
    db_session.commit()

    event = db_session.query(AuditEvent).one()
    for name in ("actor_username", "target_label", "ip", "action", "target_type"):
        column_length = AuditEvent.__table__.c[name].type.length or audit.NAME_LIMIT
        assert len(getattr(event, name)) <= column_length, name


def test_oversized_detail_is_dropped(db_session):
    audit.record_event(
        db_session,
        actor=None,
        action=audit.AuditAction.AUTH_LOGIN_FAILED,
        detail={"reason": "r" * 5000},
    )
    db_session.commit()

    assert db_session.query(AuditEvent).one().detail is None


def test_detail_dict_decodes_the_stored_json(db_session):
    audit.record_event(
        db_session,
        actor=None,
        action=audit.AuditAction.USER_ROLE_CHANGED,
        detail={"old": "member", "new": "admin"},
    )
    db_session.commit()

    assert db_session.query(AuditEvent).one().detail_dict == {"old": "member", "new": "admin"}


def test_corrupt_detail_does_not_break_the_list(client, db_session):
    db_session.add(AuditEvent(action="auth.login", detail="{not json"))
    db_session.commit()

    events = _events(client, action="auth.login")["events"]

    assert events[0]["detail"] is None


def test_huge_forwarded_for_still_signs_in(client, signed_out):
    _create_member(client)

    response = signed_out.post(
        "/api/auth/login",
        json={"username": "alice", "password": TEMPORARY},
        headers={"X-Forwarded-For": "9" * 5000},
    )

    assert response.status_code == 200
    assert len(_latest(client, "auth.login")["ip"]) <= 64


def test_huge_forwarded_for_on_a_failed_sign_in_still_returns_401(client, signed_out):
    response = signed_out.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "whatever"},
        headers={"X-Forwarded-For": "9" * 5000},
    )

    assert response.status_code == 401
    assert len(_latest(client, "auth.login_failed")["ip"]) <= 64
