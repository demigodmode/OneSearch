import pytest
from onesearch_shared import DocumentBatch, NormalizedRemoteDocument, ScanFile, ScanManifest

from app.models import Agent, Source
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
