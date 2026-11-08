# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import auth as auth_module
from app.config import settings
from app.models import AuditEvent, Source


@pytest.fixture(autouse=True)
def clear_rate_limit() -> None:
    auth_module.rate_limit_store.clear()
    yield
    auth_module.rate_limit_store.clear()


@pytest.fixture(autouse=True)
def no_path_restriction(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_source_paths", "")


@pytest.fixture
def source_dir(tmp_path) -> str:
    (tmp_path / "notes.txt").write_text("hello")
    return str(tmp_path)


@pytest.fixture
def stored_source(db_session: Session, source_dir: str) -> Source:
    source = Source(
        id="docs", name="Docs", root_path=source_dir, include_patterns="[]", exclude_patterns="[]"
    )
    db_session.add(source)
    db_session.commit()
    return source


class FakeStats:
    successful = failed = skipped = 0

    def to_dict(self) -> dict[str, int]:
        return {"successful": 0, "failed": 0, "skipped": 0}


@pytest.fixture
def fake_reindex(monkeypatch) -> None:
    class FakeDispatcher:
        def __init__(self, *args, **kwargs):
            pass

        async def dispatch(self, *args, **kwargs):
            return FakeStats()

    monkeypatch.setattr("app.api.sources.ScanDispatcher", FakeDispatcher)


def _events(db_session: Session, action: str) -> list[AuditEvent]:
    return db_session.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _only(db_session: Session, action: str) -> AuditEvent:
    rows = _events(db_session, action)
    assert len(rows) == 1, f"expected one {action} entry, found {len(rows)}"
    return rows[0]


def _count_prefix(db_session: Session, prefix: str) -> int:
    return sum(1 for row in db_session.query(AuditEvent).all() if row.action.startswith(prefix))


def _enable_agents(client: TestClient) -> None:
    assert client.put("/api/settings", json={"remote_agents_enabled": True}).status_code == 200


def _enroll_agent(client: TestClient, db_session: Session, name: str = "office-pc") -> dict:
    code = client.post("/api/agents/enrollments").json()["code"]
    response = client.post(
        "/api/agent/v1/enroll",
        json={
            "protocol_version": 3,
            "enrollment_token": code,
            "agent_name": name,
            "agent_version": "1.4.0",
            "platform": "windows-amd64",
            "allowed_roots": [{"root_id": "documents", "path": "C:/Users/Ada/Documents"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# Tokens

def test_token_create_is_logged_once_with_name_and_expiry(client, db_session):
    response = client.post("/api/auth/tokens", json={"name": "ci", "expires_in_days": 30})

    assert response.status_code == 201
    event = _only(db_session, "token.created")
    assert event.actor_username == "testuser"
    assert event.target_type == "user"
    assert event.target_label == "testuser"
    assert event.detail_dict == {"name": "ci", "expires_in_days": 30}


def test_own_token_revoke_is_logged(client, db_session):
    token_id = client.post("/api/auth/tokens", json={"name": "ci"}).json()["id"]

    assert client.delete(f"/api/auth/tokens/{token_id}").status_code == 204

    event = _only(db_session, "token.revoked")
    assert event.actor_username == "testuser"
    assert event.target_label == "testuser"
    assert event.detail_dict == {"name": "ci"}


def test_admin_revoking_a_members_token_names_the_owner(
    client, member_client, member_user, db_session
):
    token_id = member_client.post("/api/auth/tokens", json={"name": "phone"}).json()["id"]

    assert client.delete(f"/api/users/{member_user.id}/tokens/{token_id}").status_code == 204

    event = _only(db_session, "token.revoked")
    assert event.actor_username == "testuser"
    assert event.target_id == member_user.id
    assert event.target_label == "member"
    assert event.detail_dict == {"name": "phone"}


def test_failed_token_revoke_writes_nothing(client, db_session):
    assert client.delete("/api/auth/tokens/9999").status_code == 404

    assert _events(db_session, "token.revoked") == []


def test_searches_and_token_uses_are_not_logged(client, db_session, monkeypatch):
    async def search(**_kwargs):
        return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 1}

    monkeypatch.setattr("app.api.search.meili_service.search", search)
    token = client.post("/api/auth/tokens", json={"name": "script"}).json()["token"]
    db_session.query(AuditEvent).delete()
    db_session.commit()

    assert client.post(
        "/api/search", json={"q": "notes"}, headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200
    assert client.post("/api/search", json={"q": "notes"}).status_code == 200

    assert db_session.query(AuditEvent).count() == 0


# Sources

def test_source_create_is_logged_with_its_name(client, db_session, source_dir):
    response = client.post("/api/sources", json={"name": "Notes", "root_path": source_dir})

    assert response.status_code == 201
    event = _only(db_session, "source.created")
    assert event.actor_username == "testuser"
    assert event.target_type == "source"
    assert event.target_label == "Notes"


def test_source_update_is_logged_with_the_new_name(client, db_session, stored_source):
    response = client.put(f"/api/sources/{stored_source.id}", json={"name": "Documents"})

    assert response.status_code == 200
    event = _only(db_session, "source.updated")
    assert event.target_label == "Documents"


def test_source_update_with_no_changes_writes_nothing(client, db_session, stored_source):
    assert client.put(f"/api/sources/{stored_source.id}", json={"name": "Docs"}).status_code == 200

    assert _events(db_session, "source.updated") == []


def test_source_update_records_the_changed_field_names_only(client, db_session, stored_source):
    response = client.put(
        f"/api/sources/{stored_source.id}",
        json={"name": "Documents", "exclude_patterns": ["*.tmp"]},
    )

    assert response.status_code == 200
    event = _only(db_session, "source.updated")
    assert event.detail_dict == {"fields": ["exclude_patterns", "name"]}
    assert "*.tmp" not in event.detail


def test_source_delete_is_logged_with_its_name(client, db_session, stored_source, meili_spy):
    assert client.delete(f"/api/sources/{stored_source.id}").status_code == 204

    event = _only(db_session, "source.deleted")
    assert event.actor_username == "testuser"
    assert event.target_label == "Docs"


def test_reindex_is_logged_with_the_full_flag(client, db_session, stored_source, fake_reindex):
    assert client.post(f"/api/sources/{stored_source.id}/reindex?full=true").status_code == 200

    event = _only(db_session, "source.reindexed")
    assert event.target_label == "Docs"
    assert event.detail_dict == {"full": True}


def test_failed_source_changes_write_nothing(client, db_session, stored_source, fake_reindex):
    assert client.put("/api/sources/missing", json={"name": "x"}).status_code == 404
    assert client.delete("/api/sources/missing").status_code == 404
    assert client.post("/api/sources/missing/reindex").status_code == 404
    assert client.put(
        f"/api/sources/{stored_source.id}",
        json={
            "schedule_type": "cron",
            "scan_schedule": "not a cron",
            "use_default_schedule": False,
        },
    ).status_code == 400

    assert _count_prefix(db_session, "source.") == 0


def test_batch_item_that_creates_a_source_is_logged(client, db_session, source_dir, monkeypatch):
    payload = {
        "id": str(uuid4()),
        "location_type": "local",
        "common_settings": {"schedule_type": "cron", "scan_schedule": "@daily"},
        "items": [{"id": str(uuid4()), "name": "Folder A", "root_path": source_dir}],
    }
    assert client.post("/api/sources/batches", json=payload).status_code == 201
    url = f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create"

    assert client.post(url, json={}).status_code == 200
    assert client.post(url, json={}).status_code == 200

    event = _only(db_session, "source.created")
    assert event.actor_username == "testuser"
    assert event.target_label == "Folder A"


# Agents

def test_enrollment_code_is_logged(client, db_session):
    _enable_agents(client)

    assert client.post("/api/agents/enrollments").status_code == 201

    event = _only(db_session, "agent.enrollment_created")
    assert event.actor_username == "testuser"
    assert event.target_label is None


def test_enrollment_code_refused_while_agents_are_off_is_not_logged(client, db_session):
    assert client.post("/api/agents/enrollments").status_code == 409

    assert _events(db_session, "agent.enrollment_created") == []


def test_approve_disable_and_revoke_are_logged_with_the_agent_name(client, db_session):
    _enable_agents(client)
    agent_id = _enroll_agent(client, db_session)["agent_id"]

    assert client.post(f"/api/agents/{agent_id}/approve").status_code == 200
    assert client.post(f"/api/agents/{agent_id}/disable").status_code == 200
    assert client.post(f"/api/agents/{agent_id}/revoke").status_code == 200

    for action in ("agent.approved", "agent.disabled", "agent.revoked"):
        event = _only(db_session, action)
        assert event.actor_username == "testuser"
        assert event.target_type == "agent"
        assert event.target_label == "office-pc"


def test_agent_revoking_itself_is_logged_without_a_user(client, db_session):
    _enable_agents(client)
    enrolled = _enroll_agent(client, db_session)
    agent_headers = {"Authorization": f"Bearer {enrolled['agent_token']}"}

    assert client.post("/api/agent/v1/revoke-self", headers=agent_headers).status_code == 204

    event = _only(db_session, "agent.revoked")
    assert event.actor_user_id is None
    assert event.actor_username is None
    assert event.target_type == "agent"
    assert event.target_label == "office-pc"
    assert event.detail_dict == {"by": "agent"}


def test_refused_agent_transitions_write_nothing(client, db_session):
    _enable_agents(client)
    agent_id = _enroll_agent(client, db_session)["agent_id"]
    assert client.post(f"/api/agents/{agent_id}/revoke").status_code == 200
    before = _count_prefix(db_session, "agent.")

    assert client.post(f"/api/agents/{agent_id}/approve").status_code == 409
    assert client.post(f"/api/agents/{agent_id}/disable").status_code == 409
    assert client.post(f"/api/agents/{agent_id}/revoke").status_code == 409

    assert _count_prefix(db_session, "agent.") == before


def test_default_processing_mode_change_is_logged_only_when_it_changes(client, db_session):
    _enable_agents(client)
    agent_id = _enroll_agent(client, db_session)["agent_id"]

    client.patch(f"/api/agents/{agent_id}", json={"default_processing_mode": "on_server"})
    client.patch(f"/api/agents/{agent_id}", json={"default_processing_mode": "on_server"})

    event = _only(db_session, "agent.updated")
    assert event.target_label == "office-pc"
    assert event.detail_dict == {"default_processing_mode": "on_server"}


# Settings

def test_settings_change_logs_keys_and_never_values(client, db_session):
    response = client.put(
        "/api/settings",
        json={
            "readable_preview_page_chars": 8123,
            "default_scan_schedule": {"schedule_type": "cron", "scan_schedule": "@hourly"},
        },
    )

    assert response.status_code == 200
    event = _only(db_session, "settings.changed")
    assert event.actor_username == "testuser"
    assert event.detail_dict == {"keys": ["default_scan_schedule", "readable_preview_page_chars"]}
    assert "8123" not in event.detail
    assert "hourly" not in event.detail


def test_settings_that_do_not_change_are_not_logged(client, db_session):
    client.put("/api/settings", json={"show_previews": False})
    db_session.query(AuditEvent).delete()
    db_session.commit()

    assert client.put("/api/settings", json={"show_previews": False}).status_code == 200

    assert _events(db_session, "settings.changed") == []


def test_invalid_settings_are_not_logged(client, db_session):
    assert client.put("/api/settings", json={"max_text_file_size_mb": 0}).status_code == 422
    assert client.put("/api/settings", json={"max_preview_size_mb": 10}).status_code == 422

    assert _events(db_session, "settings.changed") == []


def test_settings_change_to_the_retention_days_is_logged_by_key(client, db_session):
    assert client.put("/api/settings", json={"audit_retention_days": 30}).status_code == 200

    assert _only(db_session, "settings.changed").detail_dict == {"keys": ["audit_retention_days"]}


def test_member_cannot_change_settings_so_nothing_is_logged(member_client, db_session):
    assert member_client.put("/api/settings", json={"show_previews": False}).status_code == 403

    assert _events(db_session, "settings.changed") == []
