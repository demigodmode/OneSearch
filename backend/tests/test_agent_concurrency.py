"""File-backed SQLite race regressions for durable remote jobs."""

import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Agent, AgentBatch, AgentJob, Base, Source
from app.services.agent_jobs import AgentJobService, JobConflict, JobLeaseError


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'race.db').as_posix()}", connect_args={"timeout": 5}
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    agent = Agent(
        id="agent",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
    )
    source = Source(
        id="source",
        name="Source",
        root_path="/data",
        location_type="agent",
        agent_id="agent",
        processing_mode="on_agent",
    )
    db.add_all([agent, source])
    db.commit()
    db.close()
    return engine, sessions


def test_two_sqlite_sessions_coalesce_concurrent_enqueue(tmp_path):
    engine, sessions = _database(tmp_path)
    barrier, jobs = threading.Barrier(2), []

    def worker():
        db = sessions()
        source = db.get(Source, "source")
        barrier.wait()
        jobs.append(AgentJobService(db).enqueue_scan(source, full=True).id)
        db.commit()
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    db = sessions()
    assert len(set(jobs)) == 1 and db.query(AgentJob).count() == 1
    db.close()
    engine.dispose()


def test_two_sqlite_sessions_issue_only_one_claim_lease(tmp_path):
    engine, sessions = _database(tmp_path)
    db = sessions()
    source = db.get(Source, "source")
    AgentJobService(db).enqueue_scan(source, full=True)
    db.commit()
    db.close()
    barrier, leases = threading.Barrier(2), []

    def worker():
        db = sessions()
        barrier.wait()
        lease = AgentJobService(db).claim_next("agent")
        db.commit()
        leases.append(lease)
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert sum(lease is not None for lease in leases) == 1
    engine.dispose()


def test_expired_reclaimed_job_rejects_old_lease_mutations(tmp_path):
    engine, sessions = _database(tmp_path)
    first = sessions()
    source = first.get(Source, "source")
    job = AgentJobService(first, lease_seconds=1).enqueue_scan(source, full=True)
    first.commit()
    job_id = job.id
    old = AgentJobService(first, lease_seconds=1).claim_next("agent")
    first.commit()
    job.lease_expires_at = _now().replace(year=_now().year - 1)
    first.commit()
    first.close()
    second = sessions()
    service = AgentJobService(second, lease_seconds=60)
    assert service.fail_expired_leases() == 1
    second.commit()
    new = service.claim_next("agent")
    second.commit()
    with pytest.raises(JobLeaseError):
        service.extend_lease("agent", job_id, old.lease_token)
    with pytest.raises(JobLeaseError):
        service.complete("agent", job_id, old.lease_token, "succeeded")
    assert new.lease_token != old.lease_token
    second.close()
    engine.dispose()


def test_cancelling_and_terminal_jobs_reject_stale_normal_mutations(tmp_path):
    engine, sessions = _database(tmp_path)
    db = sessions()
    source = db.get(Source, "source")
    service = AgentJobService(db)
    job = service.enqueue_scan(source, full=True)
    db.commit()
    lease = service.claim_next("agent")
    db.commit()
    service.cancel(job.id)
    db.commit()
    with pytest.raises(JobConflict):
        service.extend_lease("agent", job.id, lease.lease_token)
    with pytest.raises(JobConflict):
        service.accept_batch("agent", job.id, lease.lease_token, "late", {"documents": []})
    with pytest.raises(JobConflict):
        service.complete("agent", job.id, lease.lease_token, "succeeded")
    service.acknowledge_cancellation("agent", job.id, lease.lease_token)
    db.commit()
    with pytest.raises(JobLeaseError):
        service.acknowledge_cancellation("agent", job.id, lease.lease_token)
    assert db.query(AgentJob).filter_by(id=job.id).one().status == "cancelled"
    db.close()
    engine.dispose()


def test_batch_and_request_cancel_serialize_without_stale_receipt(tmp_path):
    engine, sessions = _database(tmp_path)
    seed = sessions()
    source = seed.get(Source, "source")
    service = AgentJobService(seed)
    job = service.enqueue_scan(source, full=True)
    seed.commit()
    lease = service.claim_next("agent")
    service.extend_lease("agent", job.id, lease.lease_token)
    seed.commit()
    job_id = job.id
    seed.close()

    barrier = threading.Barrier(2)
    outcomes = []

    def submit_batch():
        db = sessions()
        try:
            barrier.wait(timeout=3)
            try:
                ack = AgentJobService(db).accept_batch(
                    "agent", job_id, lease.lease_token, "race", {"documents": []}
                )
                db.commit()
                outcomes.append(("batch", ack.duplicate))
            except (JobConflict, JobLeaseError):
                db.rollback()
                outcomes.append(("batch_rejected", None))
        finally:
            db.close()

    def request_cancel():
        db = sessions()
        try:
            barrier.wait(timeout=3)
            AgentJobService(db).cancel(job_id)
            db.commit()
            outcomes.append(("cancel", None))
        finally:
            db.close()

    threads = [threading.Thread(target=submit_batch), threading.Thread(target=request_cancel)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    check = sessions()
    stored = check.get(AgentJob, job_id)
    receipts = check.query(AgentBatch).filter_by(job_id=job_id).count()
    assert ("cancel", None) in outcomes
    assert stored.status == "cancelling"
    assert receipts in {0, 1}
    assert (receipts == 1) == any(item[0] == "batch" for item in outcomes)
    check.close()
    engine.dispose()


def test_cancel_and_complete_cannot_resurrect_a_terminal_job(tmp_path):
    engine, sessions = _database(tmp_path)
    seed = sessions()
    source = seed.get(Source, "source")
    service = AgentJobService(seed)
    job = service.enqueue_scan(source, full=True)
    seed.commit()
    lease = service.claim_next("agent")
    service.extend_lease("agent", job.id, lease.lease_token)
    seed.commit()
    job_id = job.id
    seed.close()
    barrier = threading.Barrier(2)
    outcomes = []

    def cancel():
        db = sessions()
        try:
            barrier.wait(timeout=3)
            outcomes.append(("cancel", AgentJobService(db).cancel(job_id).status))
            db.commit()
        finally:
            db.close()

    def complete():
        db = sessions()
        try:
            barrier.wait(timeout=3)
            try:
                outcomes.append(
                    (
                        "complete",
                        AgentJobService(db)
                        .complete("agent", job_id, lease.lease_token, "succeeded")
                        .status,
                    )
                )
                db.commit()
            except (JobConflict, JobLeaseError):
                db.rollback()
                outcomes.append(("complete_rejected", None))
        finally:
            db.close()

    threads = [threading.Thread(target=cancel), threading.Thread(target=complete)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    db = sessions()
    stored = db.get(AgentJob, job_id)
    assert stored.status in {"cancelling", "completed"}
    if stored.status == "completed":
        assert stored.active_key is None and stored.lease_token_hash is None
    else:
        assert stored.active_key == "source" and stored.lease_token_hash is not None
    db.close()
    engine.dispose()
