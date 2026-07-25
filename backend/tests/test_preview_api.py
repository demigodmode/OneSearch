# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for authenticated image/RAW preview API."""

import asyncio
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
    def no_stream(*_args, **_kwargs):
        return Response(status_code=204)

    monkeypatch.setattr("app.api.preview.StreamingResponse", no_stream)
    from app.services.remote_files import remote_streams

    existing_jobs = set(remote_streams._streams)
    yield
    for job_id in set(remote_streams._streams) - existing_jobs:
        asyncio.run(remote_streams.close(job_id))


def _remote_download_link(client, document):
    response = client.post(f"/api/documents/{document['id']}/download-link")
    assert response.status_code == 200
    return response.json()["url"]


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
