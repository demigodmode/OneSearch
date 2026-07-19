# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Enrollment, approval, authentication, and heartbeat contracts."""

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Agent, AgentEnrollment, AgentJob, Base, IndexedFile, Source, User


def _enable(client, enabled=True):
    response = client.put("/api/settings", json={"remote_agents_enabled": enabled})
    assert response.status_code == 200


def _create_code(client):
    response = client.post("/api/agents/enrollments")
    assert response.status_code == 201
    return response.json()


def _enroll(client, code, *, protocol_version=1, name="office-pc", roots=None):
    return client.post(
        "/api/agent/v1/enroll",
        json={
            "protocol_version": protocol_version,
            "enrollment_token": code,
            "agent_name": name,
            "agent_version": "1.4.0",
            "platform": "windows-amd64",
            "allowed_roots": roots or [{"root_id": "documents", "path": "C:/Users/Ada/Documents"}],
        },
    )


def test_enrollment_code_is_gated_human_readable_hashed_and_short_lived(client, db_session):
    disabled = client.post("/api/agents/enrollments")
    assert disabled.status_code == 409
    assert disabled.json() == {"detail": "Remote agents are disabled"}

    _enable(client)
    body = _create_code(client)
    assert re.fullmatch(
        r"OS-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}",
        body["code"],
    )
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=14) < expires_at - datetime.now(timezone.utc) <= timedelta(minutes=15)

    stored = db_session.query(AgentEnrollment).one()
    assert stored.code_hash == hashlib.sha256(body["code"].encode()).hexdigest()
    assert body["code"] not in repr(stored.__dict__)


def test_create_enrollment_requires_user_auth_even_when_feature_is_disabled(client):
    client.headers.pop("Authorization", None)
    response = client.post("/api/agents/enrollments")
    assert response.status_code == 401


def test_enrollment_validates_before_atomically_consuming_code(client, db_session):
    _enable(client)
    code = _create_code(client)["code"]

    incompatible = _enroll(client, code, protocol_version=2)
    assert incompatible.status_code == 409
    assert db_session.query(AgentEnrollment).one().used_at is None

    enrolled = _enroll(client, code)
    assert enrolled.status_code == 201
    token = enrolled.json()["agent_token"]
    agent = db_session.query(Agent).one()
    assert agent.status == "pending"
    assert agent.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token != agent.token_hash
    assert json.loads(agent.allowed_roots) == [
        {
            "root_id": "documents",
            "path": "C:/Users/Ada/Documents",
            "display_name": None,
            "read_only": True,
        }
    ]

    reused = _enroll(client, code, name="second")
    assert reused.status_code == 409


def test_expired_code_is_rejected(client, db_session):
    _enable(client)
    code = _create_code(client)["code"]
    enrollment = db_session.query(AgentEnrollment).one()
    enrollment.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.commit()

    response = _enroll(client, code)
    assert response.status_code == 409
    assert db_session.query(AgentEnrollment).one().used_at is None


@pytest.mark.parametrize(
    "roots",
    [
        [{"root_id": "docs", "path": ""}],
        [{"root_id": "docs", "path": "C:/Docs"}, {"root_id": "docs", "path": "D:/Docs"}],
        [
            {"root_id": "docs", "path": "C:/Docs"},
            {"root_id": "docs ", "path": "D:/Docs"},
        ],
    ],
)
def test_enrollment_rejects_invalid_allowed_roots_without_consuming_code(client, db_session, roots):
    _enable(client)
    code = _create_code(client)["code"]
    response = _enroll(client, code, roots=roots)
    assert response.status_code == 422
    assert db_session.query(AgentEnrollment).one().used_at is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_name", " "),
        ("agent_name", "a" * 121),
        ("platform", "p" * 81),
        ("agent_version", "v" * 41),
    ],
)
def test_enrollment_rejects_invalid_identity_without_consuming_code(
    client, db_session, field, value
):
    _enable(client)
    code = _create_code(client)["code"]
    payload = {
        "protocol_version": 1,
        "enrollment_token": code,
        "agent_name": "office-pc",
        "agent_version": "1.4.0",
        "platform": "windows-amd64",
        "allowed_roots": [{"root_id": "documents", "path": "C:/Documents"}],
    }
    payload[field] = value

    response = client.post("/api/agent/v1/enroll", json=payload)

    assert response.status_code == 422
    assert db_session.query(AgentEnrollment).one().used_at is None


def test_admin_routes_require_user_jwt_and_reject_agent_tokens(client, db_session):
    _enable(client)
    code = _create_code(client)["code"]
    enrolled = _enroll(client, code).json()
    agent_id = enrolled["agent_id"]
    agent_headers = {"Authorization": f"Bearer {enrolled['agent_token']}"}

    routes = [
        ("post", "/api/agents/enrollments"),
        ("get", "/api/agents"),
        ("get", f"/api/agents/{agent_id}"),
        ("post", f"/api/agents/{agent_id}/approve"),
        ("post", f"/api/agents/{agent_id}/disable"),
        ("post", f"/api/agents/{agent_id}/revoke"),
    ]
    for method, path in routes:
        response = getattr(client, method)(path, headers=agent_headers)
        assert response.status_code == 401, path

    client.headers.pop("Authorization", None)
    for method, path in routes:
        response = getattr(client, method)(path)
        assert response.status_code == 401, path


def test_agent_list_and_detail_are_safe_and_admin_state_transitions_are_explicit(
    client, db_session
):
    _enable(client)
    enrolled = _enroll(client, _create_code(client)["code"]).json()
    agent_id = enrolled["agent_id"]

    listed = client.get("/api/agents")
    detail = client.get(f"/api/agents/{agent_id}")
    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [detail.json()]
    assert detail.json()["allowed_roots"][0]["root_id"] == "documents"
    assert "token_hash" not in detail.text

    approved = client.post(f"/api/agents/{agent_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "offline"
    assert approved.json()["approved_at"] is not None

    token_hash = db_session.get(Agent, agent_id).token_hash
    disabled = client.post(f"/api/agents/{agent_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert db_session.get(Agent, agent_id).token_hash == token_hash

    reapproved = client.post(f"/api/agents/{agent_id}/approve")
    assert reapproved.status_code == 200
    assert reapproved.json()["status"] == "offline"

    revoked = client.post(f"/api/agents/{agent_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert db_session.get(Agent, agent_id).token_hash is None
    assert client.post(f"/api/agents/{agent_id}/approve").status_code == 409


def test_heartbeat_authenticates_pending_then_marks_approved_agent_online(
    client, db_session, auth_headers
):
    _enable(client)
    enrolled = _enroll(client, _create_code(client)["code"]).json()
    headers = {"Authorization": f"Bearer {enrolled['agent_token']}"}
    payload = {"protocol_version": 1, "agent_version": "1.4.1", "platform": "windows-amd64"}

    client.headers.pop("Authorization", None)
    pending = client.post("/api/agent/v1/heartbeat", json=payload, headers=headers)
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert db_session.get(Agent, enrolled["agent_id"]).last_seen_at is not None

    client.headers.update(headers)
    assert client.get("/api/agents").status_code == 401
    approved = client.post(f"/api/agents/{enrolled['agent_id']}/approve", headers=auth_headers)
    assert approved.status_code == 200
    online = client.post("/api/agent/v1/heartbeat", json=payload, headers=headers)
    assert online.status_code == 200
    assert online.json()["status"] == "online"


def test_heartbeat_rejects_user_jwt_disabled_revoked_and_global_disable(
    client, db_session, auth_headers
):
    _enable(client)
    enrolled = _enroll(client, _create_code(client)["code"]).json()
    agent_id = enrolled["agent_id"]
    agent_headers = {"Authorization": f"Bearer {enrolled['agent_token']}"}
    heartbeat = {"agent_version": "1.4.0", "platform": "windows-amd64"}

    assert (
        client.post("/api/agent/v1/heartbeat", json=heartbeat, headers=auth_headers).status_code
        == 401
    )
    client.post(f"/api/agents/{agent_id}/approve", headers=auth_headers)
    online = client.post("/api/agent/v1/heartbeat", json=heartbeat, headers=agent_headers)
    assert online.status_code == 200
    assert online.json()["status"] == "online"

    client.post(f"/api/agents/{agent_id}/disable", headers=auth_headers)
    assert (
        client.post("/api/agent/v1/heartbeat", json=heartbeat, headers=agent_headers).status_code
        == 403
    )
    client.post(f"/api/agents/{agent_id}/approve", headers=auth_headers)
    _enable(client, False)
    assert (
        client.post("/api/agent/v1/heartbeat", json=heartbeat, headers=agent_headers).status_code
        == 409
    )
    assert client.get(f"/api/agents/{agent_id}", headers=auth_headers).status_code == 200
    assert client.post(f"/api/agents/{agent_id}/revoke", headers=auth_headers).status_code == 200


def test_disabling_feature_preserves_agents_sources_jobs_and_indexed_records(client, db_session):
    _enable(client)
    enrolled = _enroll(client, _create_code(client)["code"]).json()
    source = Source(
        id="remote-source",
        name="Remote",
        root_path="documents",
        location_type="agent",
        agent_id=enrolled["agent_id"],
        processing_mode="on_agent",
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(IndexedFile(source_id=source.id, path="a.txt", status="success"))
    db_session.add(
        AgentJob(
            id="job-1",
            agent_id=enrolled["agent_id"],
            source_id=source.id,
            kind="scan",
            status="pending",
        )
    )
    db_session.commit()

    _enable(client, False)
    assert db_session.query(Agent).count() == 1
    assert db_session.query(Source).count() == 1
    assert db_session.query(AgentJob).count() == 1
    assert db_session.query(IndexedFile).count() == 1


@pytest.mark.asyncio
async def test_approved_dependency_rejects_pending_agent(db_session):
    from app.services.agent_auth import require_approved_agent

    pending = Agent(
        id="agent-pending",
        name="Pending",
        platform="windows",
        version="1",
        protocol_version=1,
        token_hash="a" * 64,
        allowed_roots="[]",
        status="pending",
    )
    db_session.add(pending)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await require_approved_agent(agent=pending)
    assert exc.value.status_code == 403


def test_code_consumption_has_exactly_one_winner_across_sessions(tmp_path):
    from app.services.agent_auth import consume_enrollment_code, hash_token

    engine = create_engine(
        f"sqlite:///{tmp_path / 'enrollment-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    seed = sessions()
    try:
        user = User(username="race-admin", password_hash="unused")
        seed.add(user)
        seed.flush()
        code = "OS-ABCD-2345"
        seed.add(
            AgentEnrollment(
                id="race-code",
                code_hash=hash_token(code),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15),
                created_by_user_id=user.id,
            )
        )
        seed.commit()
    finally:
        seed.close()

    barrier = threading.Barrier(2)

    def attempt():
        db = sessions()
        try:
            barrier.wait()
            consumed = consume_enrollment_code(db, code)
            db.commit()
            return consumed
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert sorted(results) == [False, True]


def test_in_flight_heartbeat_cannot_overwrite_admin_disable(tmp_path):
    from app.services.agent_auth import record_agent_heartbeat

    engine = create_engine(
        f"sqlite:///{tmp_path / 'heartbeat-race.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    seed = sessions()
    seed.add(
        Agent(
            id="agent-race",
            name="Race",
            platform="windows",
            version="1.0",
            protocol_version=1,
            token_hash="a" * 64,
            allowed_roots="[]",
            status="offline",
            approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    seed.commit()
    seed.close()

    heartbeat_db = sessions()
    admin_db = sessions()
    try:
        authenticated = heartbeat_db.get(Agent, "agent-race")
        assert authenticated.status == "offline"
        heartbeat_db.commit()

        disabled = admin_db.get(Agent, "agent-race")
        disabled.status = "disabled"
        disabled.disabled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        admin_db.commit()

        assert (
            record_agent_heartbeat(
                heartbeat_db,
                agent_id=authenticated.id,
                version="1.1",
                platform="windows",
            )
            is None
        )
        heartbeat_db.rollback()

        check_db = sessions()
        try:
            stored = check_db.get(Agent, "agent-race")
            assert stored.status == "disabled"
            assert stored.token_hash == "a" * 64
        finally:
            check_db.close()
    finally:
        heartbeat_db.close()
        admin_db.close()
