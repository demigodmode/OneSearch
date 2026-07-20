import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Agent, Source
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
    assert json.loads(first.payload) == {"full": True}


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
    service.complete(agent.id, job.id, lease.lease_token, "succeeded")
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
