import hashlib
import json

import pytest
from onesearch_shared import DocumentBatch, NormalizedRemoteDocument, ScanFile, ScanManifest
from sqlalchemy import select

from app.models import Agent, AgentBatch, IndexedFile, Source
from app.services.agent_jobs import AgentJobService, JobConflict, JobLeaseError
from app.services.remote_ingest import (
    RemoteIngestService,
    canonical_remote_path,
    remote_document_id,
)


def test_remote_paths_are_canonical_and_ids_are_path_derived():
    assert canonical_remote_path("folder/file.txt") == "folder/file.txt"
    assert remote_document_id("source", "folder/file.txt") == remote_document_id(
        "source", "folder/file.txt"
    )


class Search:
    def __init__(self):
        self.indexed, self.deleted = [], []

    async def index_documents(self, docs):
        self.indexed.append(docs)

    async def delete_document(self, doc):
        self.deleted.append(doc)


class FailedConfirmedSearch(Search):
    async def index_documents_confirmed(self, docs):
        raise RuntimeError("indexing task failed")

    async def delete_document_confirmed(self, doc):
        raise RuntimeError("delete task failed")


class CancellingDeleteSearch(Search):
    def __init__(self, job):
        super().__init__()
        self.job = job

    async def delete_document(self, doc):
        self.deleted.append(doc)
        self.job.status = "cancelling"
        self.job.lease_expires_at = None


@pytest.fixture
def remote_job(db_session):
    agent = Agent(
        id="a",
        name="a",
        platform="x",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
        status="online",
    )
    source = Source(
        id="s",
        name="s",
        root_path="/data",
        location_type="agent",
        agent_id="a",
        processing_mode="on_agent",
    )
    db_session.add_all([agent, source])
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    return db_session, AgentJobService(db_session).claim_next("a"), job


@pytest.mark.asyncio
async def test_batch_duplicate_is_not_reindexed_and_bad_paths_are_rejected(remote_job):
    db, lease, job = remote_job
    search = Search()
    service = RemoteIngestService(db, search)
    batch = DocumentBatch(
        job_id=job.id,
        batch_id="b",
        documents=[
            NormalizedRemoteDocument(
                source_id="s", path="new.txt", content="x", modified_at=1_700_000_000_000_000_000
            )
        ],
    )
    assert (await service.accept_batch("a", job.id, lease.lease_token, batch)).duplicate is False
    assert (await service.accept_batch("a", job.id, lease.lease_token, batch)).duplicate is True
    assert len(search.indexed) == 1
    with pytest.raises(JobConflict):
        await service.accept_batch(
            "a",
            job.id,
            lease.lease_token,
            DocumentBatch(
                job_id=job.id,
                batch_id="bad",
                documents=[
                    NormalizedRemoteDocument(
                        source_id="s", path="../bad", content="x", modified_at=1
                    )
                ],
            ),
        )


def test_manifest_requires_valid_lease_and_preserves_versioned_complete_state(remote_job):
    db, lease, job = remote_job
    service = RemoteIngestService(db, Search())
    manifest = ScanManifest(
        job_id=job.id,
        source_id="s",
        files=[ScanFile(path="a.txt", size_bytes=1, modified_at=1)],
        complete=True,
    )
    service.accept_manifest("a", job.id, lease.lease_token, manifest)
    assert '"version":1' in job.checkpoint
    with pytest.raises(JobLeaseError):
        service.accept_manifest("a", job.id, "wrong", manifest)


@pytest.mark.asyncio
async def test_confirmed_index_failure_rolls_back_reserved_receipt_and_indexed_file(remote_job):
    db, lease, job = remote_job
    batch = DocumentBatch(
        job_id=job.id,
        batch_id="failed",
        documents=[
            NormalizedRemoteDocument(source_id="s", path="new.txt", content="x", modified_at=1)
        ],
    )
    with pytest.raises(RuntimeError, match="indexing task failed"):
        await RemoteIngestService(db, FailedConfirmedSearch()).accept_batch(
            "a", job.id, lease.lease_token, batch
        )
    db.rollback()
    db.expire_all()
    assert list(db.scalars(select(AgentBatch).where(AgentBatch.job_id == job.id))) == []
    assert list(db.scalars(select(IndexedFile).where(IndexedFile.source_id == "s"))) == []


@pytest.mark.asyncio
async def test_confirmed_delete_failure_preserves_job_and_old_file(remote_job):
    db, lease, job = remote_job
    old = IndexedFile(source_id="s", path="old.txt", status="success")
    db.add(old)
    db.commit()
    service = RemoteIngestService(db, FailedConfirmedSearch())
    service.accept_manifest(
        "a", job.id, lease.lease_token, ScanManifest(job_id=job.id, source_id="s", complete=True)
    )
    with pytest.raises(RuntimeError, match="delete task failed"):
        await service.reconcile_completion("a", job.id, lease.lease_token)
    db.rollback()
    db.expire_all()
    restored = db.get(type(job), job.id)
    assert (
        db.scalar(
            select(IndexedFile).where(IndexedFile.source_id == "s", IndexedFile.path == "old.txt")
        )
        is not None
    )
    assert (
        restored.status == "claimed"
        and restored.active_key == "s"
        and restored.completed_at is None
    )


@pytest.mark.asyncio
async def test_receipt_collision_same_checksum_returns_duplicate_without_losing_work(
    remote_job, monkeypatch
):
    db, lease, job = remote_job
    batch = DocumentBatch(job_id=job.id, batch_id="collision", documents=[])
    payload = json.dumps(
        batch.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    checksum = hashlib.sha256(payload.encode()).hexdigest()
    db.add(AgentBatch(job_id=job.id, idempotency_key=batch.batch_id, checksum=checksum))
    db.commit()
    original, calls = db.scalar, 0

    def hide_first(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", hide_first)
    search = Search()
    ack = await RemoteIngestService(db, search).accept_batch("a", job.id, lease.lease_token, batch)
    assert ack.duplicate is True and search.indexed == []
    db.expire_all()
    assert len(list(db.scalars(select(AgentBatch).where(AgentBatch.job_id == job.id)))) == 1
    assert list(db.scalars(select(IndexedFile).where(IndexedFile.source_id == "s"))) == []


@pytest.mark.asyncio
async def test_receipt_collision_different_checksum_conflicts_without_losing_work(
    remote_job, monkeypatch
):
    db, lease, job = remote_job
    db.add(AgentBatch(job_id=job.id, idempotency_key="collision", checksum="different"))
    db.commit()
    batch = DocumentBatch(job_id=job.id, batch_id="collision", documents=[])
    original, calls = db.scalar, 0

    def hide_first(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", hide_first)
    search = Search()
    with pytest.raises(JobConflict):
        await RemoteIngestService(db, search).accept_batch("a", job.id, lease.lease_token, batch)
    db.rollback()
    db.expire_all()
    assert len(list(db.scalars(select(AgentBatch).where(AgentBatch.job_id == job.id)))) == 1
    assert search.indexed == []
    assert list(db.scalars(select(IndexedFile).where(IndexedFile.source_id == "s"))) == []


@pytest.mark.asyncio
async def test_complete_manifest_rename_deletes_old_only_at_terminal_success(remote_job):
    db, lease, job = remote_job
    search = Search()
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    service = RemoteIngestService(db, search)
    await service.accept_batch(
        "a",
        job.id,
        lease.lease_token,
        DocumentBatch(
            job_id=job.id,
            batch_id="new",
            documents=[
                NormalizedRemoteDocument(
                    source_id="s", path="new.txt", content="new", modified_at=1
                )
            ],
        ),
    )
    service.accept_manifest(
        "a",
        job.id,
        lease.lease_token,
        ScanManifest(
            job_id=job.id,
            source_id="s",
            files=[ScanFile(path="new.txt", size_bytes=3, modified_at=1)],
            complete=True,
        ),
    )
    await service.reconcile_completion("a", job.id, lease.lease_token)
    assert search.deleted == [remote_document_id("s", "old.txt")]
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is None
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "new.txt")) is not None


@pytest.mark.asyncio
async def test_failure_manifest_paths_are_current_and_upsert_failed_rows(remote_job):
    db, lease, job = remote_job
    search = Search()
    db.add(IndexedFile(source_id="s", path="kept.txt", status="success"))
    db.commit()
    service = RemoteIngestService(db, search)
    service.accept_manifest(
        "a",
        job.id,
        lease.lease_token,
        ScanManifest(
            job_id=job.id,
            source_id="s",
            failures=[
                {"path": "kept.txt", "error": "cannot read"},
                {"path": "new.txt", "error": "cannot parse"},
            ],
            complete=True,
        ),
    )
    await service.reconcile_completion("a", job.id, lease.lease_token)
    assert search.deleted == []
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "kept.txt")).status == "failed"
    assert (
        db.scalar(select(IndexedFile).where(IndexedFile.path == "new.txt")).error_message
        == "cannot parse"
    )


def test_direct_on_agent_success_bypass_is_rejected(remote_job):
    db, lease, job = remote_job
    with pytest.raises(JobConflict):
        AgentJobService(db).complete("a", job.id, lease.lease_token, "succeeded")


@pytest.mark.asyncio
async def test_completion_race_after_external_delete_rolls_back_database_state(remote_job):
    db, lease, job = remote_job
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    service = RemoteIngestService(db, CancellingDeleteSearch(job))
    service.accept_manifest(
        "a", job.id, lease.lease_token, ScanManifest(job_id=job.id, source_id="s", complete=True)
    )
    with pytest.raises((JobConflict, JobLeaseError)):
        await service.reconcile_completion("a", job.id, lease.lease_token)
    db.rollback()
    db.expire_all()
    restored = db.get(type(job), job.id)
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None
    assert (
        restored.active_key == "s"
        and restored.status == "claimed"
        and restored.completed_at is None
    )


@pytest.mark.asyncio
async def test_partial_manifest_rejects_success_without_deleting(remote_job):
    db, lease, job = remote_job
    search = Search()
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    RemoteIngestService(db, search).accept_manifest(
        "a", job.id, lease.lease_token, ScanManifest(job_id=job.id, source_id="s", complete=False)
    )
    with pytest.raises(JobConflict):
        await RemoteIngestService(db, search).reconcile_completion("a", job.id, lease.lease_token)
    assert search.deleted == []
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None


def test_failed_and_cancelled_completion_do_not_delete_indexed_files(remote_job):
    db, lease, job = remote_job
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    AgentJobService(db).complete("a", job.id, lease.lease_token, "failed")
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None
