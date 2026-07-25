import json
from datetime import datetime, timedelta, timezone

import pytest

from app.api import agent_protocol
from app.models import Agent, AppSetting, Source
from app.services.agent_auth import create_agent_token, hash_token
from app.services.agent_jobs import AgentJobService, JobConflict, JobNotFound


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def remote(db_session):
    agent = Agent(
        id="agent-1",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
        status="online",
        approved_at=now(),
    )
    source = Source(
        id="remote-1",
        name="Remote",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_agent",
    )
    db_session.add_all([agent, source])
    db_session.commit()
    return agent, source


def test_enqueue_coalesces_one_active_scan_per_source(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    first = service.enqueue_scan(source, full=True, reason="manual")
    second = service.enqueue_scan(source, full=False, reason="schedule")
    db_session.commit()
    assert first.id == second.id
    assert first.active_key == source.id
    payload = json.loads(first.payload)
    assert payload["full"] is True
    assert payload["root_path"] == source.root_path
    assert payload["known_files"] == {}


def test_claim_issues_hashed_lease_and_rejects_wrong_agent(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=10)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    db_session.refresh(job)
    assert lease.id == job.id and lease.source_id == source.id
    assert job.status == "claimed" and job.lease_token_hash != lease.lease_token
    with pytest.raises(JobNotFound):
        service.extend_lease("other", job.id, lease.lease_token)


def test_heartbeat_extends_lease_and_expired_lease_reclaims(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=10)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.extend_lease(agent.id, job.id, lease.lease_token, completed_items=2, total_items=3)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "running" and job.progress_current == 2
    job.lease_expires_at = now() - timedelta(seconds=1)
    db_session.commit()
    assert service.fail_expired_leases() == 1
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "pending" and job.lease_token_hash is None and job.active_key == source.id


def test_batches_are_idempotent_and_checksum_conflicts(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    payload = {"job_id": job.id, "batch_id": "batch-1", "documents": []}
    assert (
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch-1", payload).duplicate
        is False
    )
    db_session.commit()
    assert (
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch-1", payload).duplicate
        is True
    )
    with pytest.raises(JobConflict):
        service.accept_batch(
            agent.id, job.id, lease.lease_token, "batch-1", {**payload, "documents": [{"x": 1}]}
        )


def test_completion_and_cancellation_clear_active_key(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.complete_reconciled_scan(agent.id, job.id, lease.lease_token)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "completed" and job.active_key is None and job.lease_token_hash is None
    pending = service.enqueue_scan(source, full=True)
    db_session.commit()
    service.cancel(pending.id)
    db_session.commit()
    db_session.refresh(pending)
    assert pending.status == "cancelled" and pending.active_key is None


def test_cancelling_job_rejects_batches_until_agent_acknowledges(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.cancel(job.id)
    db_session.commit()
    with pytest.raises(JobConflict):
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch", {"x": 1})
    service.complete(agent.id, job.id, lease.lease_token, "cancelled")
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "cancelled" and job.active_key is None


def test_expired_cancelling_job_is_finalized_and_frees_the_source(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=1)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    service.claim_next(agent.id)
    db_session.commit()
    service.cancel(job.id)
    db_session.flush()
    job.lease_expires_at = now() - timedelta(seconds=1)
    db_session.commit()
    assert service.fail_expired_leases() == 1
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "cancelled" and job.active_key is None and job.lease_token_hash is None
    assert service.enqueue_scan(source, full=True).id != job.id


def test_agent_job_api_claim_progress_batch_completion_and_cancellation_ack(
    client, db_session, remote, monkeypatch
):
    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    service = AgentJobService(db_session)

    class FakeIngest:
        async def accept_batch(self, agent_id, job_id, token, batch):
            return AgentJobService(db_session).accept_batch(
                agent_id, job_id, token, batch.batch_id, batch.model_dump(mode="json")
            )

        async def reconcile_completion(self, agent_id, job_id, token):
            AgentJobService(db_session).complete_reconciled_scan(agent_id, job_id, token)

    monkeypatch.setattr(agent_protocol, "get_remote_ingest_service", lambda db: FakeIngest())
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    claimed = client.post("/api/agent/v1/jobs/claim", headers=headers)
    assert claimed.status_code == 200
    lease = claimed.json()
    lease_headers = {**headers, "X-OneSearch-Lease-Token": lease["lease_token"]}
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/heartbeat",
            headers=lease_headers,
            json={"job_id": job.id, "completed_items": 1, "total_items": 2},
        ).status_code
        == 200
    )
    batch = {"job_id": job.id, "batch_id": "batch-1", "documents": []}
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=batch
        ).json()["duplicate"]
        is False
    )
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=batch
        ).json()["duplicate"]
        is True
    )
    nonempty = {
        "job_id": job.id,
        "batch_id": "batch-strings",
        "documents": [
            {"source_id": source.id, "path": "string-id.txt", "content": "x", "modified_at": 1}
        ],
    }
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=nonempty
        ).status_code
        == 200
    )
    changed = {
        **batch,
        "documents": [{"source_id": source.id, "path": "x", "content": "x", "modified_at": 1}],
    }
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=changed
        ).status_code
        == 409
    )
    completed = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers=lease_headers,
        json={
            "job_id": job.id,
            "status": "succeeded",
            "reason": None,
            "detail": None,
            "checkpoint": None,
        },
    )
    assert completed.status_code == 200, completed.text
    cancelled = service.enqueue_scan(source, full=True)
    db_session.commit()
    cancel_lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()
    service.cancel(cancelled.id)
    db_session.commit()
    cancel_headers = {**headers, "X-OneSearch-Lease-Token": cancel_lease["lease_token"]}
    ack = client.post(f"/api/agent/v1/jobs/{cancelled.id}/cancel-ack", headers=cancel_headers)
    assert ack.status_code == 200


def test_failed_completion_api_accepts_reason_and_persists_detail(client, db_session, remote):
    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()
    response = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers={**headers, "X-OneSearch-Lease-Token": lease["lease_token"]},
        json={"job_id": job.id, "status": "failed", "reason": "internal_error", "detail": "boom"},
    )
    assert response.status_code == 200
    assert db_session.get(type(job), job.id).status == "failed"
    assert db_session.get(type(job), job.id).error == "boom"


def test_agent_job_api_rejects_bad_agent_lease_and_disabled_feature(
    client, db_session, remote, monkeypatch
):
    from app.api import agent_protocol

    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()["lease_token"]
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/heartbeat",
            headers=headers,
            json={"job_id": job.id, "completed_items": 1},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/agent/v1/jobs/missing/heartbeat",
            headers={**headers, "X-OneSearch-Lease-Token": lease},
            json={"job_id": "missing", "completed_items": 1},
        ).status_code
        == 404
    )
    db_session.get(AppSetting, "remote_agents_enabled").value = "false"
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 409
    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 1)


def test_claim_without_work_returns_bounded_204_and_closes_poll_session(
    client, db_session, remote, monkeypatch
):
    from app.api import agent_protocol

    agent, _ = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    closed = []
    original = agent_protocol.make_claim_session

    def tracked(request_db):
        session = original(request_db)
        close = session.close

        def close_tracked():
            closed.append(True)
            close()

        session.close = close_tracked
        return session

    monkeypatch.setattr(agent_protocol, "make_claim_session", tracked)
    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 1)
    response = client.post("/api/agent/v1/jobs/claim", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    assert closed and all(closed)


@pytest.mark.asyncio
async def test_claim_poll_waits_exactly_the_configured_deadline(monkeypatch, db_session, remote):
    from app.api import agent_protocol

    agent, _ = remote
    agent.status = "online"
    agent.approved_at = now()
    timeline = [0.0]

    async def advance(seconds):
        timeline[0] += seconds

    class EmptySession:
        def close(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 25)
    monkeypatch.setattr(agent_protocol, "CLAIM_POLL_SECONDS", 1)
    monkeypatch.setattr(agent_protocol, "claim_clock", lambda: timeline[0])
    monkeypatch.setattr(agent_protocol, "claim_sleep", advance)
    monkeypatch.setattr(agent_protocol, "make_claim_session", lambda _: EmptySession())
    monkeypatch.setattr(
        agent_protocol,
        "AgentJobService",
        lambda _: type("S", (), {"claim_next": lambda *_: None})(),
    )
    response = await agent_protocol.claim_job(agent, db_session)
    assert response.status_code == 204
    assert timeline[0] == 25


def test_job_endpoints_reject_user_pending_disabled_and_revoked_agents(
    client, db_session, remote, auth_headers
):
    agent, _ = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    agent.status = "pending"
    agent.approved_at = None
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=auth_headers).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 403
    agent.status = "disabled"
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 403
    agent.status = "revoked"
    agent.token_hash = None
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 401
