import asyncio
import hashlib

import pytest


@pytest.fixture
def remote(db_session):
    from datetime import datetime, timezone

    from app.models import Agent, Source

    agent = Agent(
        id="agent-files",
        name="Agent",
        platform="windows",
        version="1",
        protocol_version=1,
        allowed_roots='[{"root_id":"r","path":"C:/files"}]',
        status="online",
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    source = Source(
        id="source-files",
        name="Remote",
        root_path="C:/files",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_server",
    )
    db_session.add_all([agent, source])
    db_session.commit()
    return agent, source


@pytest.mark.asyncio
async def test_bounded_writer_rejects_declared_size_before_reading(tmp_path):
    from app.services.remote_files import RemoteFileChanged, copy_bounded

    read = False

    async def chunks():
        nonlocal read
        read = True
        yield b"x"

    with pytest.raises(RemoteFileChanged, match="size"):
        await copy_bounded(chunks(), tmp_path / "item", expected_size=2, maximum_size=1)
    assert not read


@pytest.mark.asyncio
async def test_bounded_writer_checks_streaming_checksum_and_removes_partial_file(tmp_path):
    from app.services.remote_files import RemoteFileChanged, copy_bounded

    target = tmp_path / "item"

    async def chunks():
        yield b"hello"

    with pytest.raises(RemoteFileChanged, match="checksum"):
        await copy_bounded(
            chunks(), target, expected_size=5, maximum_size=5, expected_checksum="0" * 64
        )
    assert not target.exists()


@pytest.mark.asyncio
async def test_bounded_queue_applies_backpressure_and_eof_checksum():
    from app.services.remote_files import BoundedByteQueue

    queue = BoundedByteQueue(max_bytes=3)
    await queue.put(0, b"abc")
    blocked = asyncio.create_task(queue.put(1, b"d"))
    await asyncio.sleep(0)
    assert not blocked.done()
    assert await queue.get() == b"abc"
    await blocked
    await queue.finish(2, hashlib.sha256(b"abcd").hexdigest())
    assert await queue.get() == b"d"
    assert await queue.get() is None


@pytest.mark.asyncio
async def test_bounded_queue_rejects_out_of_order_or_changed_chunks():
    from app.services.remote_files import BoundedByteQueue, RemoteFileChanged

    queue = BoundedByteQueue(max_bytes=4)
    with pytest.raises(RemoteFileChanged, match="sequence"):
        await queue.put(1, b"a")
    with pytest.raises(RemoteFileChanged, match="checksum"):
        await queue.put(0, b"a", checksum="0" * 64)


def test_on_server_manifest_enqueues_one_extract_job_per_file(db_session, remote):
    from app.models import AgentJob
    from app.services.agent_jobs import AgentJobService

    _agent, source = remote
    source.processing_mode = "on_server"
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    created = AgentJobService(db_session).enqueue_extract_files(
        parent,
        [
            {"path": "a.txt", "size_bytes": 3, "modified_at": 4, "content_hash": "a" * 64},
            {"path": "b.txt", "size_bytes": 5, "modified_at": 6, "content_hash": None},
        ],
    )
    assert len(created) == 2
    assert {job.kind for job in created} == {"extract_file"}
    assert all(
        __import__("json").loads(job.payload)["maximum_size"] == 100 * 1024 * 1024
        for job in created
    )
    assert db_session.query(AgentJob).filter_by(kind="extract_file").count() == 2


def test_extract_upload_rejects_oversize_before_creating_temp_file(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    registry = ExtractUploadRegistry(tmp_path, chunk_bytes=4)
    with pytest.raises(RemoteFileChanged, match="chunk"):
        registry.append("job", sequence=0, data=b"12345", expected_size=5, maximum_size=5)
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_streams_to_private_temp_file_and_validates_checksum(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path, chunk_bytes=3)
    registry.append("job", sequence=0, data=b"abc", expected_size=5, maximum_size=5)
    registry.append("job", sequence=1, data=b"de", expected_size=5, maximum_size=5)
    path = registry.finish("job", sequence=2, checksum=hashlib.sha256(b"abcde").hexdigest())
    assert path.read_bytes() == b"abcde"
    registry.cleanup("job")
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_mismatch_or_expiry_leaves_no_temp_file(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    registry = ExtractUploadRegistry(tmp_path, chunk_bytes=4)
    registry.append("job", sequence=0, data=b"abc", expected_size=3, maximum_size=3)
    with pytest.raises(RemoteFileChanged):
        registry.finish("job", sequence=1, checksum="0" * 64)
    assert list(tmp_path.iterdir()) == []
    registry.append("expired", sequence=0, data=b"x", expected_size=1, maximum_size=1)
    registry.expire(0)
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_preserves_only_validated_suffix(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "job", sequence=0, data=b"x", expected_size=1, maximum_size=1, suffix=".txt"
    )
    path = registry.finish("job", sequence=1, checksum=hashlib.sha256(b"x").hexdigest())
    assert path.suffix == ".txt"
    registry.cleanup("job")


def test_on_server_parent_release_keeps_parent_nonterminal(db_session, remote):
    from app.services.agent_jobs import AgentJobService

    _agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    children = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )
    parent.status = "running"
    AgentJobService(db_session).release_on_server_parent(parent.id)
    db_session.flush()
    db_session.refresh(parent)
    assert parent.status == "running" and parent.active_key == source.id
    children[0].status = "completed"
    assert AgentJobService(db_session).settle_on_server_parent(parent.id) == "running"


@pytest.mark.asyncio
async def test_server_parent_settlement_waits_then_completes_without_children(db_session, remote):
    import json

    from onesearch_shared import ScanManifest

    from app.services.agent_jobs import AgentJobService
    from app.services.remote_ingest import RemoteIngestService

    _agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    parent.status = "running"
    parent.lease_token_hash = parent.lease_expires_at = None
    parent.checkpoint = json.dumps({"version": 1, "remote_manifest": ScanManifest(
        job_id=parent.id, source_id=source.id, complete=True
    ).model_dump(mode="json")})
    db_session.flush()

    class Search:
        async def delete_documents_confirmed(self, ids):
            assert ids == []

    result = await RemoteIngestService(db_session, Search()).settle_server_parent(parent.id)
    db_session.refresh(parent)
    assert result == "completed" and parent.active_key is None


@pytest.mark.asyncio
async def test_server_parent_failed_child_never_deletes_indexed_file(db_session, remote):
    import json

    from onesearch_shared import ScanManifest

    from app.models import IndexedFile
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_ingest import RemoteIngestService

    _agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(parent, [{"path":"a.txt","size_bytes":1,"modified_at":1,"content_hash":None}])[0]
    parent.status, parent.lease_token_hash = "running", None
    parent.checkpoint = json.dumps({"version":1,"remote_manifest":ScanManifest(job_id=parent.id, source_id=source.id, complete=True).model_dump(mode="json")})
    child.status = "failed"
    old = IndexedFile(source_id=source.id, path="old.txt", status="success")
    db_session.add(old)
    class Search:
        async def delete_documents_confirmed(self, ids): raise AssertionError("must not delete")
    assert await RemoteIngestService(db_session, Search()).settle_server_parent(parent.id) == "failed"
    assert old in db_session and parent.status == "failed"
