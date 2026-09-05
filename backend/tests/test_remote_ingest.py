import hashlib
import json

import pytest
from onesearch_shared import (
    DocumentBatch,
    NormalizedRemoteDocument,
    ScanCheckpoint,
    ScanFile,
    ScanManifestPage,
    ScanManifestPagePayload,
    ScanPageOutcome,
    ScanPageOutcomePayload,
    ScanPathOutcome,
    canonical_wire_bytes,
    remote_path_hash,
)
from sqlalchemy import select

from app.models import Agent, AgentBatch, IndexedFile, Source
from app.services.agent_jobs import AgentJobService, JobConflict
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
        self.indexed = []

    async def index_documents(self, docs):
        self.indexed.append(docs)

    async def delete_document(self, document_id):
        pass


class SearchMustNotRun(Search):
    async def index_documents(self, docs):
        raise AssertionError("empty batches must not contact search")


@pytest.fixture
def remote_job(db_session):
    agent = Agent(
        id="a",
        name="a",
        platform="x",
        version="1",
        protocol_version=3,
        allowed_roots='[{"root_id":"data","path":"/data"}]',
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
async def test_empty_batch_persists_receipt_without_contacting_search(remote_job):
    db, lease, job = remote_job
    batch = DocumentBatch(job_id=job.id, batch_id="empty", documents=[])

    ack = await RemoteIngestService(db, SearchMustNotRun()).accept_batch(
        "a", job.id, lease.lease_token, batch
    )
    db.commit()

    assert ack.accepted_count == 0
    assert (
        db.scalar(
            select(AgentBatch).where(
                AgentBatch.job_id == job.id, AgentBatch.idempotency_key == "empty"
            )
        )
        is not None
    )


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
                    NormalizedRemoteDocument(source_id="s", path="../bad", content="x", modified_at=1)
                ],
            ),
        )


@pytest.mark.asyncio
async def test_batch_requires_an_exact_v3_job_contract(remote_job):
    db, lease, job = remote_job
    job.payload = json.dumps({"protocol_version": 4})

    with pytest.raises(JobConflict, match="invalid paged scan job"):
        await RemoteIngestService(db, Search()).accept_batch(
            "a", job.id, lease.lease_token, DocumentBatch(job_id=job.id, batch_id="b", documents=[])
        )


def _manifest_page(job):
    payload = ScanManifestPagePayload(
        job_id=job.id,
        source_id=job.source_id,
        sequence=0,
        files=[
            ScanFile(path="new.txt", path_hash=remote_path_hash("new.txt"), size_bytes=1, modified_at=1)
        ],
        checkpoint=ScanCheckpoint(cursor="page:1", scanned_count=1),
        final=True,
    )
    return ScanManifestPage(
        checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(), page=payload
    )


def _settle_page(service, lease, job, *, files=None):
    page = _manifest_page(job)
    if files is not None:
        payload = page.page.model_copy(update={"files": files})
        page = ScanManifestPage(
            checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(), page=payload
        )
    service.accept_manifest_page("a", job.id, lease.lease_token, page)
    payload = ScanPageOutcomePayload(
        job_id=job.id,
        source_id="s",
        sequence=0,
        page_checksum=page.checksum,
        results=[ScanPathOutcome(path=file.path, status="skipped") for file in page.page.files],
    )
    service.accept_page_outcome(
        "a",
        job.id,
        lease.lease_token,
        ScanPageOutcome(
            checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(), outcome=payload
        ),
    )


def test_manifest_page_requires_an_exact_v3_job_contract(remote_job):
    db, lease, job = remote_job
    service = RemoteIngestService(db, Search())

    ack = service.accept_manifest_page("a", job.id, lease.lease_token, _manifest_page(job))
    assert ack.changed_paths == ["new.txt"]

    job.payload = json.dumps({"protocol_version": 4})
    with pytest.raises(JobConflict, match="invalid paged scan job"):
        RemoteIngestService(db, Search()).accept_manifest_page(
            "a", job.id, lease.lease_token, _manifest_page(job)
        )


@pytest.mark.asyncio
async def test_v3_completion_reconciles_only_durable_final_pages(remote_job):
    db, lease, job = remote_job
    service = RemoteIngestService(db, Search())
    page = _manifest_page(job)
    service.accept_manifest_page("a", job.id, lease.lease_token, page)
    outcome_payload = ScanPageOutcomePayload(
        job_id=job.id,
        source_id="s",
        sequence=0,
        page_checksum=page.checksum,
        results=[ScanPathOutcome(path="new.txt", status="skipped")],
    )
    outcome = ScanPageOutcome(
        checksum=hashlib.sha256(canonical_wire_bytes(outcome_payload)).hexdigest(),
        outcome=outcome_payload,
    )
    service.accept_page_outcome("a", job.id, lease.lease_token, outcome)
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()

    await service.reconcile_completion("a", job.id, lease.lease_token)

    assert job.status == "completed"
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is None


@pytest.mark.asyncio
async def test_v3_unsettled_page_blocks_completion_without_deleting(remote_job):
    db, lease, job = remote_job
    search = Search()
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    RemoteIngestService(db, search).accept_manifest_page("a", job.id, lease.lease_token, _manifest_page(job))

    with pytest.raises(JobConflict, match="complete manifest required"):
        await RemoteIngestService(db, search).reconcile_completion("a", job.id, lease.lease_token)

    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None


@pytest.mark.asyncio
async def test_v3_confirmed_delete_failure_rolls_back_completion_guard(remote_job):
    db, lease, job = remote_job

    class FailingDelete(Search):
        async def delete_documents_confirmed(self, _ids):
            raise RuntimeError("delete task failed")

    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    service = RemoteIngestService(db, FailingDelete())
    _settle_page(service, lease, job, files=[])
    with pytest.raises(RuntimeError, match="delete task failed"):
        await service.reconcile_completion("a", job.id, lease.lease_token)
    db.rollback()
    db.expire_all()
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None
    restored = db.get(type(job), job.id)
    assert restored.status == "claimed" and restored.completed_at is None


@pytest.mark.asyncio
async def test_v3_reconciliation_removes_all_preview_variants_for_missing_file(
    remote_job, tmp_path, monkeypatch
):
    from app.services.preview_assets import store_preview

    db, lease, job = remote_job
    preview_root = tmp_path / "previews"
    monkeypatch.setattr(
        "app.services.remote_ingest.app_data_preview_directory", lambda _database_url: preview_root
    )
    old = IndexedFile(source_id="s", path="old.jpg", status="success", modified_at_ns=1)
    db.add(old)
    db.commit()
    first = store_preview("s", "old.jpg", b"first", preview_root, 1)
    second = store_preview("s", "old.jpg", b"second", preview_root, 2)
    assert first is not None and second is not None and second.exists()

    service = RemoteIngestService(db, Search())
    _settle_page(service, lease, job, files=[])
    await service.reconcile_completion("a", job.id, lease.lease_token)

    assert not first.exists() and not second.exists()
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.jpg")) is None


@pytest.mark.asyncio
async def test_v3_cancelled_scan_never_deletes_indexed_files(remote_job):
    db, lease, job = remote_job
    db.add(IndexedFile(source_id="s", path="old.txt", status="success"))
    db.commit()
    AgentJobService(db).cancel(job.id)
    AgentJobService(db).acknowledge_cancellation("a", job.id, lease.lease_token)
    db.commit()
    assert db.scalar(select(IndexedFile).where(IndexedFile.path == "old.txt")) is not None


def test_v3_incremental_jobs_do_not_embed_known_file_inventory(remote_job):
    db, _lease, job = remote_job
    db.add(IndexedFile(source_id="s", path="precise.txt", modified_at_ns=1_700_000_000_123_456_789))
    job.status, job.active_key, job.lease_expires_at = "completed", None, None
    db.commit()

    payload = json.loads(AgentJobService(db).enqueue_scan(db.get(Source, "s"), full=False).payload)

    assert payload["protocol_version"] == 3
    assert "known_files" not in payload
    assert "max_scan_files" not in payload["limits"]
