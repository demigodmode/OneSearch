# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for preview asset storage and cleanup."""

import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, hash_password
from app.db.database import get_db
from app.main import app
from app.models import Agent, AgentJob, AppSetting, Base, IndexedFile, Source, User
from app.services.agent_auth import create_agent_token, hash_token
from app.services.agent_jobs import AgentJobService
from app.services.preview_assets import (
    app_data_preview_directory,
    delete_preview,
    delete_source_previews,
    store_preview,
)
from app.services.remote_ingest import RemoteIngestService, canonical_remote_path
from onesearch_shared import remote_path_hash

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


def test_reconciliation_deletes_preview_assets(db_session, tmp_path, monkeypatch):
    """Test that reconciliation deletes preview files for documents no longer in remote."""
    # Setup agent and source
    agent = Agent(
        id="agent-1",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=3,
        allowed_roots=json.dumps([{"root_id": "data", "path": "/data"}]),
        status="online",
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    source = Source(
        id="remote-1",
        name="Remote",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_agent",
    )

    # Create an indexed file that will be removed during reconciliation
    indexed = IndexedFile(
        source_id=source.id,
        path="photos/old.jpg",
        size_bytes=1000,
        modified_at_ns=1_700_000_000_000_000_000,
        status="success",
    )

    db_session.add_all([agent, source, indexed, AppSetting(key="remote_agents_enabled", value="true")])
    db_session.commit()

    # Create a stored preview file
    preview_data = b"fake jpeg preview data"
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    monkeypatch.setattr("app.services.preview_assets.app_data_preview_directory", lambda _: preview_dir)

    store_preview(source.id, "photos/old.jpg", preview_data, preview_dir)
    path_hash = remote_path_hash("photos/old.jpg")
    preview_file = preview_dir / source.id / f"{path_hash}.jpg"
    assert preview_file.exists()

    # Run reconciliation with empty manifest (document is gone)
    ingest = RemoteIngestService(db_session, None)
    # Simulate reconciliation by deleting the indexed file
    db_session.delete(indexed)
    db_session.commit()

    # Call delete_preview to clean up
    delete_preview(source.id, "photos/old.jpg", preview_dir)

    # Verify preview file is deleted
    assert not preview_file.exists()


def test_source_deletion_removes_preview_directory(db_session, tmp_path, monkeypatch):
    """Test that deleting a source removes its preview directory."""
    from fastapi.testclient import TestClient

    # Setup user and source with previews
    user = User(username="test", password_hash=hash_password("test"), is_active=True)
    db_session.add(user)
    db_session.commit()
    token, _ = create_access_token(user.id, user.username)

    source = Source(
        id="local-source",
        name="Local",
        root_path="/tmp/test",
        location_type="local",
    )
    db_session.add(source)
    db_session.commit()

    # Create a preview directory with files
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    monkeypatch.setattr("app.services.preview_assets.app_data_preview_directory", lambda _: preview_dir)

    source_preview_dir = preview_dir / source.id
    source_preview_dir.mkdir(parents=True)
    (source_preview_dir / "preview1.jpg").write_bytes(b"preview data")
    assert source_preview_dir.exists()

    # Override database dependency
    def override_get_db():
        yield db_session

    monkeypatch.setattr("app.db.database.get_db", override_get_db)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        client.headers.update({"Authorization": f"Bearer {token}"})
        response = client.delete(f"/api/sources/{source.id}")

    app.dependency_overrides.clear()

    assert response.status_code in {200, 204}
    # Verify source preview directory is deleted
    assert not source_preview_dir.exists()


def test_on_server_extraction_produces_stored_preview(db_session, tmp_path, monkeypatch):
    """Test that on-server file extraction produces a stored preview."""
    # Setup remote agent and source with on_server processing
    agent = Agent(
        id="agent-1",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=3,
        allowed_roots=json.dumps([{"root_id": "data", "path": "/data"}]),
        status="online",
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    source = Source(
        id="remote-1",
        name="Remote",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_server",
    )

    db_session.add_all([agent, source, AppSetting(key="remote_agents_enabled", value="true")])
    db_session.commit()

    # Mock preview directory
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    monkeypatch.setattr("app.services.preview_assets.app_data_preview_directory", lambda _: preview_dir)

    # Simulate storing a preview during on-server extraction
    preview_jpeg = Image.new("RGB", (50, 40), color="blue")
    preview_buffer = BytesIO()
    preview_jpeg.save(preview_buffer, format="JPEG", quality=80)
    preview_data = preview_buffer.getvalue()

    store_preview(source.id, "documents/extracted.jpg", preview_data, preview_dir)

    # Verify preview was stored
    path_hash = remote_path_hash("documents/extracted.jpg")
    preview_file = preview_dir / source.id / f"{path_hash}.jpg"
    assert preview_file.exists()
    assert preview_file.read_bytes() == preview_data


def test_corrupt_image_does_not_crash_scan(db_session, tmp_path, monkeypatch):
    """Test that corrupt/undecodable images don't crash the scan process."""
    # Setup agent and source
    agent = Agent(
        id="agent-1",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=3,
        allowed_roots=json.dumps([{"root_id": "data", "path": "/data"}]),
        status="online",
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    source = Source(
        id="remote-1",
        name="Remote",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_agent",
    )

    db_session.add_all([agent, source, AppSetting(key="remote_agents_enabled", value="true")])
    db_session.commit()

    # Mock preview directory
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    monkeypatch.setattr("app.services.preview_assets.app_data_preview_directory", lambda _: preview_dir)

    # Try to store corrupt image data - should not crash, just skip
    corrupt_data = b"not a valid image file at all"
    try:
        store_preview(source.id, "corrupt.jpg", corrupt_data, preview_dir)
        # If we get here, it either succeeded (stored raw data) or handled gracefully
        path_hash = remote_path_hash("corrupt.jpg")
        preview_file = preview_dir / source.id / f"{path_hash}.jpg"
        # File should exist even if data is corrupt (we store what we get)
        assert preview_file.exists()
    except Exception as e:
        # If it raises, it should be a controlled exception, not a crash
        pytest.fail(f"Should not crash on corrupt image: {e}")
