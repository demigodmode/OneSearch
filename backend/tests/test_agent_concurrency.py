"""File-backed SQLite race regressions for durable remote jobs."""

import asyncio
import threading
from datetime import datetime, timezone

import pytest
from onesearch_shared import DocumentBatch, NormalizedRemoteDocument
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Agent, AgentBatch, AgentJob, Base, IndexedFile, Source
from app.services.agent_jobs import AgentJobService, JobConflict, JobLeaseError
from app.services.remote_ingest import RemoteIngestService


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


def _capture(errors, worker):
    try:
        worker()
    except BaseException as error:
        errors.append(error)


def test_two_sqlite_sessions_coalesce_concurrent_enqueue(tmp_path):
    engine, sessions = _database(tmp_path)
    barrier, jobs, errors = threading.Barrier(2), [], []

    def worker():
        db = sessions()
        source = db.get(Source, "source")
        barrier.wait()
        jobs.append(AgentJobService(db).enqueue_scan(source, full=True).id)
        db.commit()
        db.close()

    threads = [threading.Thread(target=_capture, args=(errors, worker)) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join(timeout=10) for thread in threads]
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
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
    barrier, leases, errors = threading.Barrier(2), [], []

    def worker():
        db = sessions()
        barrier.wait()
        lease = AgentJobService(db).claim_next("agent")
        db.commit()
        leases.append(lease)
        db.close()

    threads = [threading.Thread(target=_capture, args=(errors, worker)) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join(timeout=10) for thread in threads]
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
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
    outcomes, errors = [], []

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

    threads = [
        threading.Thread(target=_capture, args=(errors, submit_batch)),
        threading.Thread(target=_capture, args=(errors, request_cancel)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert errors == []
    check = sessions()
    stored = check.get(AgentJob, job_id)
    receipts = check.query(AgentBatch).filter_by(job_id=job_id).count()
    assert ("cancel", None) in outcomes
    assert stored.status == "cancelling"
    assert receipts in {0, 1}
    assert (receipts == 1) == any(item[0] == "batch" for item in outcomes)
    check.close()
    engine.dispose()


def test_remote_ingest_batch_lock_serializes_confirmed_index_and_cancel(tmp_path):
    engine, sessions = _database(tmp_path)
    seed = sessions()
    source = seed.get(Source, "source")
    service = AgentJobService(seed)
    job = service.enqueue_scan(source, full=True)
    seed.commit()
    lease = service.claim_next("agent")
    seed.commit()
    job_id = job.id
    seed.close()

    index_started, release_index, cancel_committed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    errors, outcomes = [], []

    class SuspendedConfirmedSearch:
        def __init__(self):
            self.indexed = []

        async def index_documents_confirmed(self, documents):
            self.indexed.append(documents)
            index_started.set()
            assert release_index.wait(timeout=5)

    search = SuspendedConfirmedSearch()
    batch = DocumentBatch(
        job_id=job_id,
        batch_id="serialized",
        documents=[
            NormalizedRemoteDocument(
                source_id="source", path="new.txt", content="body", modified_at=1
            )
        ],
    )

    def submit_batch():
        db = sessions()
        try:
            ack = asyncio.run(
                RemoteIngestService(db, search).accept_batch(
                    "agent", job_id, lease.lease_token, batch
                )
            )
            db.commit()
            outcomes.append(("batch", ack.duplicate))
        finally:
            db.close()

    def request_cancel():
        db = sessions()
        try:
            assert index_started.wait(timeout=5)
            AgentJobService(db).cancel(job_id)
            db.commit()
            cancel_committed.set()
            outcomes.append(("cancel", None))
        finally:
            db.close()

    batch_thread = threading.Thread(target=_capture, args=(errors, submit_batch))
    cancel_thread = threading.Thread(target=_capture, args=(errors, request_cancel))
    batch_thread.start()
    assert index_started.wait(timeout=5)
    cancel_thread.start()
    assert not cancel_committed.wait(timeout=0.2)
    release_index.set()
    for thread in (batch_thread, cancel_thread):
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert errors == []
    assert ("batch", False) in outcomes and ("cancel", None) in outcomes
    check = sessions()
    assert check.get(AgentJob, job_id).status == "cancelling"
    assert check.query(AgentBatch).filter_by(job_id=job_id).count() == 1
    assert check.query(IndexedFile).filter_by(source_id="source", path="new.txt").count() == 1
    assert len(search.indexed) == 1
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
    outcomes, errors = [], []

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

    threads = [
        threading.Thread(target=_capture, args=(errors, cancel)),
        threading.Thread(target=_capture, args=(errors, complete)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert errors == []
    db = sessions()
    stored = db.get(AgentJob, job_id)
    assert stored.status in {"cancelling", "completed"}
    if stored.status == "completed":
        assert stored.active_key is None and stored.lease_token_hash is None
    else:
        assert stored.active_key == "source" and stored.lease_token_hash is not None
    db.close()
    engine.dispose()
