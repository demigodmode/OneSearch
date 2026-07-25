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
