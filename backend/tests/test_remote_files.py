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

    queue = BoundedByteQueue(max_bytes=3, expected_size=4)
    await queue.put(0, b"abc", hashlib.sha256(b"abc").hexdigest())
    blocked = asyncio.create_task(queue.put(1, b"d", hashlib.sha256(b"d").hexdigest()))
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

    queue = BoundedByteQueue(max_bytes=4, expected_size=1)
    with pytest.raises(RemoteFileChanged, match="checksum"):
        await queue.put(0, b"a")
    with pytest.raises(RemoteFileChanged, match="sequence"):
        await queue.put(1, b"a", checksum=hashlib.sha256(b"a").hexdigest())
    with pytest.raises(RemoteFileChanged, match="checksum"):
        await queue.put(0, b"a", checksum="0" * 64)


@pytest.mark.asyncio
async def test_bounded_queue_enforces_exact_total_size_including_zero_byte_streams():
    from app.services.remote_files import BoundedByteQueue, RemoteFileChanged

    queue = BoundedByteQueue(max_bytes=2, expected_size=2)
    await queue.put(0, b"ab", hashlib.sha256(b"ab").hexdigest())
    assert await queue.get() == b"ab"  # consuming buffered bytes does not change total received
    await queue.finish(1, hashlib.sha256(b"ab").hexdigest())
    zero = BoundedByteQueue(max_bytes=1, expected_size=0)
    await zero.finish(0, hashlib.sha256(b"").hexdigest())
    under = BoundedByteQueue(max_bytes=2, expected_size=2)
    await under.put(0, b"a", hashlib.sha256(b"a").hexdigest())
    with pytest.raises(RemoteFileChanged, match="size"):
        under.validate_finish(1, hashlib.sha256(b"a").hexdigest())
    over = BoundedByteQueue(max_bytes=3, expected_size=1)
    with pytest.raises(RemoteFileChanged, match="size"):
        await over.put(0, b"ab", hashlib.sha256(b"ab").hexdigest())


@pytest.mark.asyncio
async def test_bounded_queue_failure_unblocks_waiting_consumer():
    from app.services.remote_files import BoundedByteQueue, RemoteFileMissing

    queue = BoundedByteQueue(max_bytes=1, expected_size=0)
    waiting = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    await queue.fail(RemoteFileMissing("missing"))
    with pytest.raises(RemoteFileMissing):
        await waiting


@pytest.mark.asyncio
async def test_bounded_queue_failure_unblocks_backpressured_producer():
    from app.services.remote_files import BoundedByteQueue, RemoteStreamTimeout

    queue = BoundedByteQueue(max_bytes=1, expected_size=2)
    await queue.put(0, b"a", hashlib.sha256(b"a").hexdigest())
    blocked = asyncio.create_task(queue.put(1, b"b", hashlib.sha256(b"b").hexdigest()))
    await asyncio.sleep(0)
    await queue.fail(RemoteStreamTimeout("closed"))
    with pytest.raises(RemoteStreamTimeout):
        await blocked


@pytest.mark.asyncio
async def test_stream_registry_close_removes_entry_and_wakes_waiter():
    from app.services.remote_files import RemoteStreamRegistry, RemoteStreamTimeout

    registry = RemoteStreamRegistry()
    queue = registry.open("job", expected_size=0)
    waiting = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    await registry.close("job")
    assert registry.get("job") is None
    with pytest.raises(RemoteStreamTimeout):
        await waiting


@pytest.mark.asyncio
async def test_stream_registry_reopens_fresh_and_requires_existing_stream():
    from app.services.remote_files import RemoteStreamRegistry, RemoteStreamTimeout

    registry = RemoteStreamRegistry()
    first = registry.open("job", expected_size=1)
    assert registry.open("job", expected_size=1) is first and registry.require("job") is first
    await registry.close("job")
    with pytest.raises(RemoteStreamTimeout):
        registry.require("job")
    second = registry.open("job", expected_size=1)
    assert second is not first
    await second.put(0, b"x", hashlib.sha256(b"x").hexdigest())
    assert await second.get() == b"x"


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
        registry.append(
            "job",
            sequence=0,
            data=b"12345",
            checksum=hashlib.sha256(b"12345").hexdigest(),
            expected_size=5,
            maximum_size=5,
        )
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_rejects_empty_chunk_without_creating_temp_file(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    with pytest.raises(RemoteFileChanged, match="chunk"):
        ExtractUploadRegistry(tmp_path).append(
            "job",
            sequence=0,
            data=b"",
            checksum=hashlib.sha256(b"").hexdigest(),
            expected_size=1,
            maximum_size=1,
        )
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_rejects_missing_or_changed_chunk_checksum_before_writing(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    registry = ExtractUploadRegistry(tmp_path)
    with pytest.raises(RemoteFileChanged, match="checksum"):
        registry.append(
            "job", sequence=0, data=b"x", checksum=None, expected_size=1, maximum_size=1
        )
    with pytest.raises(RemoteFileChanged, match="checksum"):
        registry.append(
            "job", sequence=0, data=b"x", checksum="0" * 64, expected_size=1, maximum_size=1
        )
    assert not registry.has("job") and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_extract_upload_write_failures_clean_exact_session(tmp_path, monkeypatch, failure):
    from app.services import remote_files
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    class FailingHandle:
        def __init__(self, path):
            self.name = str(path)

        def write(self, _data):
            if failure == "write":
                raise OSError("write failed")

        def flush(self):
            if failure == "flush":
                raise OSError("flush failed")

        def close(self):
            pass

    registry = ExtractUploadRegistry(tmp_path)
    first_path = tmp_path / "first"
    first_path.touch()
    monkeypatch.setattr(
        remote_files.tempfile, "NamedTemporaryFile", lambda **_kwargs: FailingHandle(first_path)
    )
    with pytest.raises(OSError, match=failure):
        registry.append(
            "first",
            sequence=0,
            data=b"x",
            checksum=hashlib.sha256(b"x").hexdigest(),
            expected_size=1,
            maximum_size=1,
        )
    assert not registry.has("first") and not first_path.exists()

    monkeypatch.undo()
    registry.append(
        "other",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=2,
    )
    registry.append(
        "later",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=2,
        maximum_size=2,
    )
    registry._sessions["later"].handle = FailingHandle(tmp_path / "later-failure")
    with pytest.raises(OSError, match=failure):
        registry.append(
            "later",
            sequence=1,
            data=b"y",
            checksum=hashlib.sha256(b"y").hexdigest(),
            expected_size=2,
            maximum_size=2,
        )
    assert not registry.has("later") and registry.has("other")
    registry.append(
        "job",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=2,
        maximum_size=2,
    )
    with pytest.raises(RemoteFileChanged, match="checksum"):
        registry.append(
            "job", sequence=1, data=b"y", checksum="0" * 64, expected_size=2, maximum_size=2
        )
    assert not registry.has("job") and registry.has("other")


def test_coordinator_cancels_children_and_cleans_uploads(db_session, remote, tmp_path):
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileCoordinator

    agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    children = AgentJobService(db_session).enqueue_extract_files(
        parent,
        [
            {"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None},
            {"path": "b.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None},
        ],
    )
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    children[1].status = "running"
    uploads = ExtractUploadRegistry(tmp_path)
    for child in children:
        uploads.append(
            child.id,
            sequence=0,
            data=b"x",
            checksum=hashlib.sha256(b"x").hexdigest(),
            expected_size=1,
            maximum_size=1,
        )
    db_session.flush()
    coordinator = RemoteFileCoordinator(db_session, uploads)
    coordinator.cancel_server_parent(parent.id)
    assert children[0].status == "cancelled" and children[1].status == "cancelling"
    assert (
        parent.status == "cancelling"
        and not uploads.has(children[0].id)
        and not uploads.has(children[1].id)
    )
    coordinator.cancel_server_parent(parent.id)
    assert children[0].status == "cancelled" and children[1].status == "cancelling"


def test_extract_upload_streams_to_private_temp_file_and_validates_checksum(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path, chunk_bytes=3)
    registry.append(
        "job",
        sequence=0,
        data=b"abc",
        checksum=hashlib.sha256(b"abc").hexdigest(),
        expected_size=5,
        maximum_size=5,
    )
    registry.append(
        "job",
        sequence=1,
        data=b"de",
        checksum=hashlib.sha256(b"de").hexdigest(),
        expected_size=5,
        maximum_size=5,
    )
    path = registry.finish("job", sequence=2, checksum=hashlib.sha256(b"abcde").hexdigest())
    assert path.read_bytes() == b"abcde"
    registry.cleanup("job")
    assert list(tmp_path.iterdir()) == []


def test_extract_upload_mismatch_or_expiry_leaves_no_temp_file(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, RemoteFileChanged

    registry = ExtractUploadRegistry(tmp_path, chunk_bytes=4)
    registry.append(
        "job",
        sequence=0,
        data=b"abc",
        checksum=hashlib.sha256(b"abc").hexdigest(),
        expected_size=3,
        maximum_size=3,
    )
    with pytest.raises(RemoteFileChanged):
        registry.finish("job", sequence=1, checksum="0" * 64)
    assert list(tmp_path.iterdir()) == []
    registry.append(
        "expired",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )
    registry.expire(0)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_extract_upload_sweeper_expires_only_stale_sessions(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry, sweep_extract_uploads

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "stale",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )
    registry.append(
        "active",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )
    registry._sessions["stale"].touched_at -= 61
    calls = []

    async def stop_after_first_sleep(seconds):
        calls.append(seconds)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await sweep_extract_uploads(
            registry, maximum_age=60, interval=5, sleep=stop_after_first_sleep
        )
    assert calls == [5]
    assert not registry.has("stale") and registry.has("active")
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_shutdown_stops_sweeper_and_cleans_all_extract_uploads(tmp_path):
    from app.main import stop_extract_upload_sweeper
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "job",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )
    started = asyncio.Event()

    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())
    await started.wait()
    await stop_extract_upload_sweeper(task, registry)
    assert task.cancelled()
    assert not registry.has("job") and list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_shutdown_cleans_uploads_when_sweeper_has_failed(tmp_path):
    from app.main import stop_extract_upload_sweeper
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "job",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )

    async def fail():
        raise RuntimeError("sweeper failed")

    task = asyncio.create_task(fail())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="sweeper failed"):
        await stop_extract_upload_sweeper(task, registry)
    assert not registry.has("job") and list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_lifespan_cleans_uploads_and_stops_scheduler_after_body_error(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from app import main
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "job",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
    )
    scheduler = type(
        "Scheduler",
        (),
        {"start": lambda self: None, "shutdown": lambda self: setattr(self, "stopped", True)},
    )()
    scheduler.stopped = False

    async def wait_forever(_registry):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "extract_uploads", registry)
    monkeypatch.setattr(main, "sweep_extract_uploads", wait_forever)
    monkeypatch.setattr(main, "SchedulerService", lambda _engine: scheduler)
    with pytest.raises(RuntimeError, match="body failed"):
        async with main.lifespan(FastAPI()):
            raise RuntimeError("body failed")
    assert scheduler.stopped
    assert not registry.has("job") and list(tmp_path.iterdir()) == []


def test_extract_upload_preserves_only_validated_suffix(tmp_path):
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    registry.append(
        "job",
        sequence=0,
        data=b"x",
        checksum=hashlib.sha256(b"x").hexdigest(),
        expected_size=1,
        maximum_size=1,
        suffix=".txt",
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
    parent.checkpoint = json.dumps(
        {
            "version": 1,
            "remote_manifest": ScanManifest(
                job_id=parent.id, source_id=source.id, complete=True
            ).model_dump(mode="json"),
        }
    )
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
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.active_key = "completed", None
    parent.status, parent.lease_token_hash = "running", None
    parent.checkpoint = json.dumps(
        {
            "version": 1,
            "remote_manifest": ScanManifest(
                job_id=parent.id, source_id=source.id, complete=True
            ).model_dump(mode="json"),
        }
    )
    child.status = "failed"
    old = IndexedFile(source_id=source.id, path="old.txt", status="success")
    db_session.add(old)

    class Search:
        async def delete_documents_confirmed(self, ids):
            raise AssertionError("must not delete")

    assert (
        await RemoteIngestService(db_session, Search()).settle_server_parent(parent.id) == "failed"
    )
    assert old in db_session and parent.status == "failed"


def test_extract_fanout_retry_coalesces_and_changed_manifest_conflicts(db_session, remote):
    from app.services.agent_jobs import AgentJobService, JobConflict

    _agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    files = [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    assert len(AgentJobService(db_session).enqueue_extract_files(parent, files)) == 1
    assert len(AgentJobService(db_session).enqueue_extract_files(parent, files)) == 1
    assert (
        db_session.query(__import__("app.models", fromlist=["AgentJob"]).AgentJob)
        .filter_by(kind="extract_file")
        .count()
        == 1
    )
    parent.checkpoint = '{"version":1,"remote_manifest":{"files":[{"path":"a.txt"}]}}'
    with pytest.raises(JobConflict):
        AgentJobService(db_session).validate_manifest_retry(parent, {"files": [{"path": "b.txt"}]})


@pytest.mark.asyncio
async def test_server_document_rejects_child_parent_source_mismatch_before_receipt(
    db_session, remote
):
    from types import SimpleNamespace

    from app.services.agent_jobs import AgentJobService, JobConflict
    from app.services.remote_ingest import RemoteIngestService

    agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    assert lease.id == child.id
    child.payload = child.payload.replace(parent.id, "wrong-parent")
    db_session.commit()

    class Search:
        async def index_documents_confirmed(self, docs):
            raise AssertionError("must not index")

    with pytest.raises(JobConflict):
        await RemoteIngestService(db_session, Search()).accept_server_document(
            agent.id,
            child.id,
            lease.lease_token,
            SimpleNamespace(source_id=source.id, path="a.txt"),
        )


@pytest.mark.asyncio
async def test_server_rename_confirmed_delete_failure_rolls_back_and_retries(db_session, remote):
    import json

    from onesearch_shared import ScanFile, ScanManifest, remote_path_hash

    from app.models import IndexedFile
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_ingest import RemoteIngestService, remote_document_id

    _agent, source = remote
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    parent.status, parent.lease_token_hash = "running", None
    parent.checkpoint = json.dumps(
        {
            "version": 1,
            "remote_manifest": ScanManifest(
                job_id=parent.id,
                source_id=source.id,
                complete=True,
                files=[
                    ScanFile(
                        path="new.txt",
                        path_hash=remote_path_hash("new.txt"),
                        size_bytes=1,
                        modified_at=1,
                    )
                ],
            ).model_dump(mode="json"),
        }
    )
    old, new = (
        IndexedFile(source_id=source.id, path="old.txt", status="success"),
        IndexedFile(source_id=source.id, path="new.txt", status="success"),
    )
    db_session.add_all([old, new])
    db_session.commit()
    calls = []

    class Search:
        async def delete_documents_confirmed(self, ids):
            calls.append(ids)
            if len(calls) == 1:
                raise RuntimeError("down")

    service = RemoteIngestService(db_session, Search())
    with pytest.raises(RuntimeError):
        await service.settle_server_parent(parent.id)
    db_session.refresh(parent)
    assert (
        parent.status == "running"
        and parent.active_key == source.id
        and db_session.get(IndexedFile, old.id)
    )
    assert await service.settle_server_parent(parent.id) == "completed"
    assert calls == [
        [remote_document_id(source.id, "old.txt")],
        [remote_document_id(source.id, "old.txt")],
    ]
    assert (
        db_session.get(IndexedFile, old.id) is None
        and db_session.get(IndexedFile, new.id) is not None
    )
