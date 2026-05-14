# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for authenticated image/RAW preview API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from io import BytesIO

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, hash_password
from app.db.database import get_db
from app.main import app
from app.models import AppSetting, Base, Source, User


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


def test_raw_preview_returns_unavailable_without_embedded_jpeg(client, source, temp_source, monkeypatch):
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
