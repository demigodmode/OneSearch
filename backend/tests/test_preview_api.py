# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for authenticated image/RAW preview API."""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from meilisearch.models.document import Document as MeiliDocument
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, hash_password
from app.db.database import get_db
from app.main import app
from app.models import Agent, AgentJob, AppSetting, Base, IndexedFile, Source, User

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def auth_headers(db_session):
    user = User(username="previewer", password_hash=hash_password("testpass"), is_active=True)
    db_session.add(user)
    db_session.commit()
    token, _ = create_access_token(user.id, user.username)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.headers.update(auth_headers)
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def temp_source():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        image_path = root / "photo.jpg"
        Image.new("RGB", (8, 6), color="blue").save(image_path)
        raw_path = root / "photo.CR3"
        raw_path.write_bytes(b"fake raw")
        yield root, image_path, raw_path


@pytest.fixture
def source(db_session, temp_source):
    root, _, _ = temp_source
    item = Source(
        id="photos",
        name="Photos",
        root_path=str(root),
        include_patterns=json.dumps(["**/*"]),
        exclude_patterns=json.dumps([]),
    )
    db_session.add(item)
    db_session.commit()
    return item


def image_doc(source, image_path):
    return {
        "id": "photos--image123",
        "source_id": source.id,
        "source_name": source.name,
        "path": str(image_path),
        "basename": image_path.name,
        "extension": "jpg",
        "type": "image",
        "size_bytes": image_path.stat().st_size,
        "modified_at": 1700000000,
        "indexed_at": 1700000000,
        "content": "photo",
        "title": "photo",
        "metadata": {},
    }


def raw_doc(source, raw_path):
    doc = image_doc(source, raw_path)
    doc.update({"id": "photos--raw123", "extension": "cr3", "type": "raw_image"})
    return doc


@pytest.fixture
def remote_download(db_session, monkeypatch):
    agent = Agent(
        id="remote-download-agent",
        name="Remote download agent",
        platform="linux",
        version="1",
        protocol_version=1,
        allowed_roots=json.dumps([{"root_id": "photos", "path": "remote/photos"}]),
        status="online",
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    source = Source(
        id="remote-download-source",
        name="Remote photos",
        root_path="remote/photos",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_server",
    )
    indexed = IndexedFile(
        source_id=source.id,
        path="albums/precise.jpg",
        size_bytes=987_654,
        modified_at_ns=1_700_000_000_123_456_789,
        status="success",
    )
    db_session.add_all(
        [agent, source, indexed, AppSetting(key="remote_agents_enabled", value="true")]
    )
    db_session.commit()
    document = {
        "id": "remote-download-source--precise",
        "source_id": source.id,
        "path": indexed.path,
        "basename": "precise.jpg",
        "size_bytes": 1,
        "modified_at": 1_700_000_000,
    }

    async def get_document(document_id):
        assert document_id == document["id"]
        return document

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)
    return agent, source, indexed, document


@pytest.fixture
def capture_remote_download_response(monkeypatch):
    from app.services.remote_files import remote_streams

    def no_stream(*_args, **_kwargs):
        return Response(status_code=204)

    original_open = remote_streams.open

    def open_and_feed(job_id, **kwargs):
        queue = original_open(job_id, **kwargs)

        async def feed():
            await queue.put(0, b"x", hashlib.sha256(b"x").hexdigest())
            await queue.finish(1, hashlib.sha256(b"x").hexdigest())

        asyncio.get_running_loop().create_task(feed())
        return queue

    monkeypatch.setattr(remote_streams, "open", open_and_feed)
    monkeypatch.setattr("app.api.preview.StreamingResponse", no_stream)

    existing_jobs = set(remote_streams._streams)
    yield
    for job_id in set(remote_streams._streams) - existing_jobs:
        asyncio.run(remote_streams.close(job_id))


def _remote_download_link(client, document):
    response = client.post(f"/api/documents/{document['id']}/download-link")
    assert response.status_code == 200
    return response.json()["url"]


@pytest.fixture
def streaming_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.headers.update(auth_headers)
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def remote_queue_feeder(monkeypatch):
    from app.api import preview

    original_open = preview.remote_streams.open

    def install(feed):
        def open_and_feed(job_id, **kwargs):
            queue = original_open(job_id, **kwargs)
            asyncio.get_running_loop().create_task(feed(queue))
            return queue

        monkeypatch.setattr(preview.remote_streams, "open", open_and_feed)

    return install


@pytest.fixture
def clean_remote_streams():
    from app.services.remote_files import remote_streams

    existing_jobs = set(remote_streams._streams)
    yield
    for job_id in set(remote_streams._streams) - existing_jobs:
        asyncio.run(remote_streams.close(job_id))


@pytest.mark.asyncio
async def test_preview_requires_authentication(unauthenticated_client):
    response = unauthenticated_client.get("/api/documents/anything/preview")

    assert response.status_code == 401


def test_preview_requires_indexed_document(client, monkeypatch):
    async def missing_document(document_id):
        return None

    monkeypatch.setattr("app.api.preview.meili_service.get_document", missing_document)

    response = client.get("/api/documents/missing/preview")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"


def test_preview_streams_indexed_standard_image(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source

    async def get_document(document_id):
        return image_doc(source, image_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--image123/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == image_path.read_bytes()


def test_download_link_requires_authentication(unauthenticated_client):
    response = unauthenticated_client.post("/api/documents/anything/download-link")

    assert response.status_code == 401


def test_download_link_requires_indexed_document(client, monkeypatch):
    async def missing_document(document_id):
        return None

    monkeypatch.setattr("app.api.preview.meili_service.get_document", missing_document)

    response = client.post("/api/documents/missing/download-link")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"


def test_download_requires_signed_token(client):
    response = client.get("/api/documents/photos--image123/download")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "download_token_missing"


def test_download_rejects_path_outside_indexed_source(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source
    with TemporaryDirectory() as outside_tmp:
        outside_file = Path(outside_tmp) / "escape.txt"
        outside_file.write_text("nope", encoding="utf-8")

        async def get_document(document_id):
            doc = image_doc(source, image_path)
            doc["path"] = str(outside_file)
            doc["basename"] = outside_file.name
            return doc

        monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

        link_response = client.post("/api/documents/photos--image123/download-link")
        assert link_response.status_code == 403
        assert link_response.json()["detail"]["code"] == "path_outside_source"


def test_download_returns_missing_file_error(client, source, temp_source, monkeypatch):
    root, image_path, _ = temp_source
    missing_path = root / "missing.pdf"

    async def get_document(document_id):
        doc = image_doc(source, image_path)
        doc["path"] = str(missing_path)
        doc["basename"] = missing_path.name
        return doc

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.post("/api/documents/photos--image123/download-link")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


def test_download_streams_original_file_from_signed_link(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source

    async def get_document(document_id):
        return image_doc(source, image_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    link_response = client.post("/api/documents/photos--image123/download-link")
    assert link_response.status_code == 200
    body = link_response.json()
    assert body["expires_in"] == 60
    assert body["url"].startswith("/api/documents/photos--image123/download?token=")

    response = client.get(body["url"])

    assert response.status_code == 200
    assert response.content == image_path.read_bytes()
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="photo.jpg"' in response.headers["content-disposition"]


@pytest.mark.parametrize("agent_state", ["offline", "pending", "disabled", "revoked", "missing"])
def test_remote_download_link_rejects_unavailable_agent_without_enqueuing(
    client, db_session, remote_download, agent_state
):
    agent, source, _indexed, document = remote_download
    if agent_state == "missing":
        source.agent_id = "missing-agent"
    else:
        agent.status = agent_state
    db_session.commit()

    response = client.post(f"/api/documents/{document['id']}/download-link")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_remote_download_link_rejects_global_opt_out_without_enqueuing(
    client, db_session, remote_download
):
    _agent, source, _indexed, document = remote_download
    db_session.query(AppSetting).filter_by(key="remote_agents_enabled").update({"value": "false"})
    db_session.commit()

    response = client.post(f"/api/documents/{document['id']}/download-link")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_remote_download_link_mints_existing_signed_contract_without_enqueuing(
    client, db_session, remote_download
):
    _agent, source, _indexed, document = remote_download

    response = client.post(f"/api/documents/{document['id']}/download-link")

    assert response.status_code == 200
    assert response.json()["expires_in"] == 60
    assert response.json()["url"].startswith(f"/api/documents/{document['id']}/download?token=")
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_remote_download_rechecks_availability_after_link_creation(
    client, db_session, remote_download, capture_remote_download_response
):
    agent, source, _indexed, document = remote_download
    url = _remote_download_link(client, document)
    agent.status = "offline"
    db_session.commit()

    response = client.get(url)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_remote_download_job_uses_exact_indexed_file_metadata(
    client, db_session, remote_download, capture_remote_download_response
):
    _agent, source, indexed, document = remote_download
    url = _remote_download_link(client, document)

    response = client.get(url)

    assert response.status_code == 204
    jobs = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").all()
    assert len(jobs) == 1
    payload = json.loads(jobs[0].payload)
    assert payload["path"] == indexed.path
    assert payload["size_bytes"] == indexed.size_bytes
    assert payload["modified_at"] == indexed.modified_at_ns


@pytest.mark.parametrize(
    ("indexed_status", "expected_status", "expected_code"),
    [
        (None, 404, "remote_file_missing"),
        ("failed", 409, "remote_file_changed"),
        ("skipped", 409, "remote_file_changed"),
    ],
)
def test_remote_download_refuses_missing_or_non_success_indexed_file(
    client,
    db_session,
    remote_download,
    capture_remote_download_response,
    indexed_status,
    expected_status,
    expected_code,
):
    _agent, source, indexed, document = remote_download
    if indexed_status is None:
        db_session.delete(indexed)
    else:
        indexed.status = indexed_status
    db_session.commit()
    url = _remote_download_link(client, document)

    response = client.get(url)

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_independent_remote_downloads_use_distinct_stream_jobs(
    client, db_session, remote_download, capture_remote_download_response
):
    _agent, source, _indexed, document = remote_download
    first = _remote_download_link(client, document)
    second = _remote_download_link(client, document)

    assert client.get(first).status_code == 204
    assert client.get(second).status_code == 204
    jobs = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").all()
    assert len(jobs) == 2
    assert len({job.id for job in jobs}) == 2


def test_remote_download_streams_chunks_with_queue_shim(
    streaming_client, db_session, remote_download, remote_queue_feeder, tmp_path
):
    _agent, source, indexed, document = remote_download
    payload = b"first bounded chunk" + b"second bounded chunk"
    indexed.size_bytes = len(payload)
    db_session.commit()

    async def feed(queue):
        await queue.put(0, payload[:19], hashlib.sha256(payload[:19]).hexdigest())
        await queue.put(1, payload[19:], hashlib.sha256(payload[19:]).hexdigest())
        await queue.finish(2, hashlib.sha256(payload).hexdigest())

    remote_queue_feeder(feed)
    url = _remote_download_link(streaming_client, document)
    response = streaming_client.get(url)

    assert response.status_code == 200 and response.content == payload
    assert response.headers["content-disposition"].startswith("attachment;")
    job = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").one()
    assert job.status == "pending"
    from app.services.remote_files import remote_streams

    assert remote_streams.get(job.id) is None and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        ("missing", 404, "remote_file_missing"),
        ("changed", 409, "remote_file_changed"),
    ],
)
def test_remote_download_first_terminal_error_is_structured(
    streaming_client,
    db_session,
    remote_download,
    remote_queue_feeder,
    error,
    expected_status,
    expected_code,
):
    from app.services.remote_files import RemoteFileChanged, RemoteFileMissing, remote_streams

    _agent, source, _indexed, document = remote_download

    async def feed(queue):
        await queue.fail(
            RemoteFileMissing("missing") if error == "missing" else RemoteFileChanged("changed")
        )

    remote_queue_feeder(feed)
    response = streaming_client.get(_remote_download_link(streaming_client, document))

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    job = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").one()
    assert job.status in {"failed", "cancelled"} and remote_streams.get(job.id) is None


@pytest.mark.asyncio
async def test_remote_stream_body_timeout_cancels_job_and_releases_queue(
    db_session, remote_download, monkeypatch, tmp_path, clean_remote_streams
):
    from app.api import preview
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import remote_streams

    _agent, source, _indexed, document = remote_download
    job = AgentJobService(db_session).enqueue_stream_file(
        source, path=document["path"], size_bytes=1, modified_at=1
    )
    queue = remote_streams.open(job.id, expected_size=1)
    db_session.commit()
    monkeypatch.setattr(preview, "REMOTE_STREAM_FIRST_CHUNK_TIMEOUT_SECONDS", 0.01, raising=False)

    class WaitingRequest:
        async def is_disconnected(self):
            return False

    stream = preview._stream_remote_body(WaitingRequest(), db_session, job, queue)
    with pytest.raises(preview.RemoteStreamTimeout):
        await anext(stream)

    assert (
        job.status == "cancelled" and job.active_key is None and remote_streams.get(job.id) is None
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_leased_stream_endpoint_feeds_browser_body_and_completes_durably(
    client, db_session, remote_download
):
    from app.api import preview
    from app.services.agent_auth import create_agent_token, hash_token
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import remote_streams

    agent, source, _indexed, document = remote_download
    payload = b"browser-stream"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    job = AgentJobService(db_session).enqueue_stream_file(
        source, path=document["path"], size_bytes=len(payload), modified_at=1
    )
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    queue = remote_streams.open(job.id, expected_size=len(payload))

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    body = preview._stream_remote_body(ConnectedRequest(), db_session, job, queue)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    try:
        chunk = await asyncio.to_thread(
            client.put,
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=0&checksum={hashlib.sha256(payload).hexdigest()}",
            content=payload,
            headers=headers,
        )
        terminal = await asyncio.to_thread(
            client.put,
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=1&complete=true&stream_checksum={hashlib.sha256(payload).hexdigest()}",
            headers=headers,
        )
        assert chunk.status_code == terminal.status_code == 200
        assert await anext(body) == payload
        with pytest.raises(StopAsyncIteration):
            await anext(body)
        db_session.refresh(job)
        assert job.status == "completed" and job.active_key is None and job.lease_token_hash is None
        assert remote_streams.get(job.id) is None
    finally:
        await body.aclose()
        await remote_streams.close(job.id)


def test_remote_preview_streams_standard_image_without_attachment(
    streaming_client, db_session, remote_download, remote_queue_feeder
):
    _agent, source, _indexed, document = remote_download
    document.update({"type": "image", "extension": "jpg"})
    payload = b"remote jpeg bytes"

    async def feed(queue):
        await queue.put(0, payload, hashlib.sha256(payload).hexdigest())
        await queue.finish(1, hashlib.sha256(payload).hexdigest())

    remote_queue_feeder(feed)
    response = streaming_client.get(f"/api/documents/{document['id']}/preview")

    assert response.status_code == 200 and response.content == payload
    assert response.headers["content-type"] == "image/jpeg"
    assert "content-disposition" not in response.headers
    job = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").one()
    from app.services.remote_files import remote_streams

    assert remote_streams.get(job.id) is None


@pytest.mark.parametrize("unavailable", ["offline", "disabled", "global_opt_out"])
def test_remote_preview_rejects_unavailable_agent_without_job(
    streaming_client, db_session, remote_download, unavailable
):
    agent, source, _indexed, document = remote_download
    document.update({"type": "image", "extension": "jpg"})
    if unavailable == "global_opt_out":
        db_session.query(AppSetting).filter_by(key="remote_agents_enabled").update(
            {"value": "false"}
        )
    else:
        agent.status = unavailable
    db_session.commit()

    response = streaming_client.get(f"/api/documents/{document['id']}/preview")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_offline"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


def test_remote_preview_enforces_exact_indexed_file_size_before_job(
    streaming_client, db_session, remote_download
):
    _agent, source, indexed, document = remote_download
    document.update({"type": "image", "extension": "jpg", "size_bytes": 1})
    indexed.size_bytes = 26 * 1024 * 1024
    db_session.add(AppSetting(key="max_preview_size_mb", value="25"))
    db_session.commit()

    response = streaming_client.get(f"/api/documents/{document['id']}/preview")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "preview_too_large"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


@pytest.mark.asyncio
async def test_remote_stream_body_disconnect_cancels_and_unblocks_producer(
    db_session, remote_download, tmp_path, clean_remote_streams
):
    from app.api import preview
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import RemoteStreamTimeout, remote_streams

    _agent, source, _indexed, document = remote_download
    job = AgentJobService(db_session).enqueue_stream_file(
        source, path=document["path"], size_bytes=1, modified_at=1
    )
    queue = remote_streams.open(job.id, expected_size=2, max_bytes=1)
    await queue.put(0, b"x", hashlib.sha256(b"x").hexdigest())
    blocked_producer = asyncio.create_task(queue.put(1, b"y", hashlib.sha256(b"y").hexdigest()))
    db_session.commit()

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    stream = preview._stream_remote_body(DisconnectedRequest(), db_session, job, queue)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    with pytest.raises(RemoteStreamTimeout):
        await blocked_producer
    assert (
        job.status == "cancelled" and job.active_key is None and remote_streams.get(job.id) is None
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_remote_stream_body_task_cancellation_closes_registered_queue(
    db_session, remote_download, tmp_path, clean_remote_streams
):
    from app.api import preview
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import remote_streams

    _agent, source, _indexed, document = remote_download
    job = AgentJobService(db_session).enqueue_stream_file(
        source, path=document["path"], size_bytes=1, modified_at=1
    )
    queue = remote_streams.open(job.id, expected_size=1)
    db_session.commit()

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    stream = preview._stream_remote_body(ConnectedRequest(), db_session, job, queue)
    next_chunk = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    next_chunk.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_chunk
    assert (
        job.status == "cancelled" and job.active_key is None and remote_streams.get(job.id) is None
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_remote_stream_body_preserves_typed_error_after_durable_failure(
    db_session, remote_download, clean_remote_streams
):
    from app.api import preview
    from app.services.agent_jobs import AgentJobService
    from app.services.remote_files import RemoteFileMissing, remote_streams

    agent, source, _indexed, document = remote_download
    jobs = AgentJobService(db_session)
    job = jobs.enqueue_stream_file(source, path=document["path"], size_bytes=1, modified_at=1)
    db_session.commit()
    lease = jobs.claim_next(agent.id)
    db_session.commit()
    jobs.complete(agent.id, job.id, lease.lease_token, "failed", error="remote_file_missing")
    db_session.commit()
    queue = remote_streams.open(job.id, expected_size=1)
    await queue.fail(RemoteFileMissing("remote file missing"))

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    stream = preview._stream_remote_body(ConnectedRequest(), db_session, job, queue)
    with pytest.raises(RemoteFileMissing):
        await anext(stream)
    db_session.refresh(job)
    assert job.status == "failed" and remote_streams.get(job.id) is None


def test_remote_preview_infers_extension_from_relative_path(
    streaming_client, db_session, remote_download, remote_queue_feeder
):
    _agent, _source, _indexed, document = remote_download
    document.update({"type": "image"})
    document.pop("extension", None)

    async def feed(queue):
        await queue.put(0, b"jpg", hashlib.sha256(b"jpg").hexdigest())
        await queue.finish(1, hashlib.sha256(b"jpg").hexdigest())

    remote_queue_feeder(feed)
    response = streaming_client.get(f"/api/documents/{document['id']}/preview")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_remote_response_wrapper_closes_body_after_prefetched_chunk(
    db_session, remote_download, remote_queue_feeder, clean_remote_streams
):
    from app.api import preview
    from app.services.remote_files import remote_streams

    _agent, source, indexed, document = remote_download

    async def feed(queue):
        await queue.put(0, b"first", hashlib.sha256(b"first").hexdigest())

    remote_queue_feeder(feed)

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    response = await preview._remote_file_response(
        request=ConnectedRequest(),
        source=source,
        document=document,
        size_bytes=indexed.size_bytes,
        modified_at=indexed.modified_at_ns,
        media_type="application/octet-stream",
        filename="x.txt",
        db=db_session,
    )
    assert await anext(response.body_iterator) == b"first"
    await response.body_iterator.aclose()
    job = db_session.query(AgentJob).filter_by(source_id=source.id, kind="stream_file").one()
    assert (
        job.status == "cancelled" and job.active_key is None and remote_streams.get(job.id) is None
    )


def test_remote_download_content_disposition_encodes_malicious_basename(
    streaming_client, remote_download, remote_queue_feeder
):
    _agent, _source, _indexed, document = remote_download
    document["basename"] = 'evil"\r\nX-Injected: yes.jpg'

    async def feed(queue):
        await queue.put(0, b"x", hashlib.sha256(b"x").hexdigest())
        await queue.finish(1, hashlib.sha256(b"x").hexdigest())

    remote_queue_feeder(feed)
    response = streaming_client.get(_remote_download_link(streaming_client, document))

    assert response.status_code == 200
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]


def test_download_rejects_token_for_different_document(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source

    async def get_document(document_id):
        return image_doc(source, image_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    link_response = client.post("/api/documents/photos--image123/download-link")
    token = link_response.json()["url"].split("token=", 1)[1]

    response = client.get(f"/api/documents/photos--other/download?token={token}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "download_token_wrong_document"


def test_preview_accepts_meilisearch_document_object(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source

    async def get_document(document_id):
        return MeiliDocument(image_doc(source, image_path))

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--image123/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_preview_rejects_path_outside_indexed_source(client, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source
    with TemporaryDirectory() as outside_tmp:
        outside_image = Path(outside_tmp) / "escape.jpg"
        Image.new("RGB", (4, 4), color="red").save(outside_image)

        async def get_document(document_id):
            doc = image_doc(source, image_path)
            doc["path"] = str(outside_image)
            return doc

        monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

        response = client.get("/api/documents/photos--image123/preview")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_outside_source"


def test_preview_enforces_max_preview_size(client, db_session, source, temp_source, monkeypatch):
    _, image_path, _ = temp_source
    db_session.add(AppSetting(key="max_preview_size_mb", value="25"))
    db_session.commit()

    async def get_document(document_id):
        doc = image_doc(source, image_path)
        doc["size_bytes"] = 26 * 1024 * 1024
        return doc

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--image123/preview")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "preview_too_large"


def test_raw_preview_streams_embedded_jpeg(client, source, temp_source, monkeypatch):
    root, _, _ = temp_source
    raw_path = root / "embedded.CR3"
    jpeg_buffer = BytesIO()
    Image.new("RGB", (5, 5), color="green").save(jpeg_buffer, format="JPEG")
    jpeg_bytes = jpeg_buffer.getvalue()
    raw_path.write_bytes(b"raw-prefix" + jpeg_bytes + b"raw-suffix")

    async def get_document(document_id):
        return raw_doc(source, raw_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--raw123/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == jpeg_bytes


def test_raw_preview_uses_largest_embedded_jpeg(client, source, temp_source, monkeypatch):
    root, _, _ = temp_source
    raw_path = root / "multiple-previews.CR3"
    small_buffer = BytesIO()
    large_buffer = BytesIO()
    Image.new("RGB", (4, 4), color="red").save(small_buffer, format="JPEG")
    Image.new("RGB", (80, 60), color="purple").save(large_buffer, format="JPEG", quality=95)
    small_jpeg = small_buffer.getvalue()
    large_jpeg = large_buffer.getvalue()
    raw_path.write_bytes(b"raw-prefix" + small_jpeg + b"raw-middle" + large_jpeg + b"raw-suffix")

    async def get_document(document_id):
        return raw_doc(source, raw_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--raw123/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == large_jpeg
    assert len(large_jpeg) > len(small_jpeg)


def test_raw_preview_returns_unavailable_without_embedded_jpeg(
    client, source, temp_source, monkeypatch
):
    _, _, raw_path = temp_source

    async def get_document(document_id):
        return raw_doc(source, raw_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)

    response = client.get("/api/documents/photos--raw123/preview")

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "raw_preview_unavailable"


def test_raw_preview_scans_in_chunks_until_embedded_jpeg(client, source, temp_source, monkeypatch):
    root, _, _ = temp_source
    raw_path = root / "late-preview.CR3"
    jpeg_buffer = BytesIO()
    Image.new("RGB", (5, 5), color="yellow").save(jpeg_buffer, format="JPEG")
    jpeg_bytes = jpeg_buffer.getvalue()
    raw_path.write_bytes((b"x" * 200_000) + jpeg_bytes + b"tail")
    read_sizes = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        f = real_open(self, *args, **kwargs)
        real_read = f.read

        def tracking_read(size=-1):
            read_sizes.append(size)
            return real_read(size)

        f.read = tracking_read
        return f

    async def get_document(document_id):
        return raw_doc(source, raw_path)

    monkeypatch.setattr("app.api.preview.meili_service.get_document", get_document)
    monkeypatch.setattr(Path, "open", tracking_open)

    response = client.get("/api/documents/photos--raw123/preview")

    assert response.status_code == 200
    assert response.content == jpeg_bytes
    assert read_sizes
    assert all(0 < size <= 65536 for size in read_sizes)
