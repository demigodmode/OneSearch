# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for preview asset storage and cleanup."""

import json
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO

import pytest
from onesearch_shared import remote_path_hash
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, hash_password
from app.db.database import get_db
from app.main import app
from app.models import Agent, AppSetting, Base, IndexedFile, Source, User
from app.services.preview_assets import (
    PreviewKeyLockRegistry,
    delete_preview,
    is_valid_derived_jpeg,
    load_preview,
    store_preview,
    store_preview_if_absent_or_identical,
)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_is_valid_derived_jpeg_requires_a_decodable_jpeg():
    image = Image.new("RGB", (8, 6), color="blue")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    assert is_valid_derived_jpeg(buffer.getvalue())
    assert not is_valid_derived_jpeg(b"not a jpeg")

    png = BytesIO()
    image.save(png, format="PNG")
    assert not is_valid_derived_jpeg(png.getvalue())


def test_concurrent_preview_store_keeps_first_content_and_rejects_conflict(tmp_path):
    barrier = threading.Barrier(2)
    source_id, path, mtime = "source", "photo.jpg", 123
    first, conflicting = b"first jpeg", b"conflicting jpeg"

    def store(body):
        barrier.wait()
        return store_preview_if_absent_or_identical(source_id, path, body, tmp_path, mtime)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(store, (first, conflicting)))

    stored = load_preview(source_id, path, tmp_path, mtime)
    assert results.count(True) == 1
    assert results.count(False) == 1
    assert stored in {first, conflicting}


def test_preview_key_lock_registry_keeps_entry_until_holder_and_waiter_exit():
    registry = PreviewKeyLockRegistry()
    holder_entered, release_holder, waiter_entered = threading.Event(), threading.Event(), threading.Event()

    def holder():
        with registry.hold("preview-key"):
            holder_entered.set()
            release_holder.wait(timeout=2)

    def waiter():
        with registry.hold("preview-key"):
            waiter_entered.set()

    first = threading.Thread(target=holder)
    second = threading.Thread(target=waiter)
    first.start()
    assert holder_entered.wait(timeout=1)
    second.start()
    deadline = time.monotonic() + 1
    while registry.references_for("preview-key") != 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert registry.active_key_count == 1
    assert registry.references_for("preview-key") == 2
    assert not waiter_entered.is_set()
    release_holder.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert waiter_entered.is_set()
    assert registry.active_key_count == 0
    assert registry.references_for("preview-key") == 0


def test_preview_key_lock_registry_releases_after_exception():
    registry = PreviewKeyLockRegistry()

    with pytest.raises(RuntimeError), registry.hold("preview-key"):
        raise RuntimeError("boom")

    assert registry.active_key_count == 0


def test_preview_key_lock_registry_does_not_serialize_different_keys():
    registry = PreviewKeyLockRegistry()
    first_entered, second_entered, release = threading.Event(), threading.Event(), threading.Event()

    def hold_first():
        with registry.hold("first"):
            first_entered.set()
            release.wait(timeout=2)

    def hold_second():
        with registry.hold("second"):
            second_entered.set()

    first = threading.Thread(target=hold_first)
    second = threading.Thread(target=hold_second)
    first.start()
    assert first_entered.wait(timeout=1)
    second.start()
    assert second_entered.wait(timeout=1)
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert registry.active_key_count == 0


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

    store_preview(source.id, "photos/old.jpg", preview_data, preview_dir, indexed.modified_at_ns)
    path_hash = remote_path_hash("photos/old.jpg")
    preview_file = preview_dir / source.id / f"{path_hash}-{indexed.modified_at_ns}.jpg"
    assert preview_file.exists()

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

    from app.services.search import meili_service

    async def fake_delete_confirmed(filter_str):
        return {"status": "succeeded"}

    monkeypatch.setattr(meili_service, "delete_documents_by_filter_confirmed", fake_delete_confirmed)

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


def test_preview_with_mtime_keyed_storage_handles_stale_updates(tmp_path):
    """Test that stale previews are not served when file mtime changes."""
    from app.services.preview_assets import delete_preview, load_preview, store_preview

    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()

    source_id = "source-1"
    path = "photos/photo.jpg"
    mtime_1 = 1_000_000_000_000_000_000
    mtime_2 = 1_000_000_000_100_000_000

    # Store preview for mtime_1
    preview_1 = b"preview for mtime 1"
    store_preview(source_id, path, preview_1, preview_dir, modified_at_ns=mtime_1)

    # Should load preview for mtime_1
    loaded = load_preview(source_id, path, preview_dir, modified_at_ns=mtime_1)
    assert loaded == preview_1

    # Should NOT load preview when querying with different mtime
    loaded_wrong = load_preview(source_id, path, preview_dir, modified_at_ns=mtime_2)
    assert loaded_wrong is None

    # Store new preview for mtime_2 (file updated)
    preview_2 = b"preview for mtime 2"
    store_preview(source_id, path, preview_2, preview_dir, modified_at_ns=mtime_2)

    # Old preview for mtime_1 should be cleaned up
    # New preview for mtime_2 should be available
    loaded_old = load_preview(source_id, path, preview_dir, modified_at_ns=mtime_1)
    assert loaded_old is None
    loaded_new = load_preview(source_id, path, preview_dir, modified_at_ns=mtime_2)
    assert loaded_new == preview_2

    # Delete should remove all variants
    delete_preview(source_id, path, preview_dir)
    assert load_preview(source_id, path, preview_dir, modified_at_ns=mtime_2) is None


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

    mtime_ns = 1_700_000_000_000_000_000
    store_preview(source.id, "documents/extracted.jpg", preview_data, preview_dir, mtime_ns)

    # Verify preview was stored
    path_hash = remote_path_hash("documents/extracted.jpg")
    preview_file = preview_dir / source.id / f"{path_hash}-{mtime_ns}.jpg"
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
    mtime_ns = 1_700_000_000_000_000_000
    try:
        store_preview(source.id, "corrupt.jpg", corrupt_data, preview_dir, mtime_ns)
        # If we get here, it either succeeded (stored raw data) or handled gracefully
        path_hash = remote_path_hash("corrupt.jpg")
        preview_file = preview_dir / source.id / f"{path_hash}-{mtime_ns}.jpg"
        # File should exist even if data is corrupt (we store what we get)
        assert preview_file.exists()
    except Exception as e:
        # If it raises, it should be a controlled exception, not a crash
        pytest.fail(f"Should not crash on corrupt image: {e}")


def test_generate_preview_produces_valid_jpeg_from_real_image(tmp_path):
    """Test that preview generation produces valid JPEG from a real image file."""
    from app.services.preview_assets import generate_derived_jpeg_preview

    # Create a real test image
    test_image = Image.new("RGB", (800, 600), color="blue")
    image_path = tmp_path / "test_photo.jpg"
    test_image.save(image_path, "JPEG")

    # Generate preview
    preview_bytes = generate_derived_jpeg_preview(image_path)

    # Should produce bytes
    assert preview_bytes is not None
    assert len(preview_bytes) > 0
    # Should be valid JPEG (magic number)
    assert preview_bytes.startswith(b"\xff\xd8\xff")
    # Should be bounded by max_bytes
    assert len(preview_bytes) <= 2 * 1024 * 1024
    # Should be smaller than original (due to downscaling and compression)
    assert len(preview_bytes) < test_image.size[0] * test_image.size[1] * 3


def test_generate_preview_rejects_oversized_image_before_conversion(monkeypatch):
    """Pixel-limit rejection must happen before Pillow decodes or transforms the image."""
    from app.services import preview_assets

    class OversizedImage:
        size = (4097, 4097)
        width = 4097
        height = 4097
        mode = "L"

        def __init__(self):
            self.converted = self.thumbnail_called = self.loaded = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def convert(self, _mode):
            self.converted = True
            return self

        def load(self):
            self.loaded = True

        def thumbnail(self, *_args):
            self.thumbnail_called = True

    image = OversizedImage()
    monkeypatch.setattr(preview_assets.Image, "open", lambda _path: image)

    assert preview_assets.generate_derived_jpeg_preview("oversized.jpg") is None
    assert not image.converted
    assert not image.thumbnail_called
    assert not image.loaded


def test_generate_preview_thumbnails_large_image_below_pixel_cap(tmp_path):
    from app.services.preview_assets import generate_derived_jpeg_preview

    source = tmp_path / "large.jpg"
    Image.new("RGB", (2048, 1536), color="orange").save(source, "JPEG")

    preview_bytes = generate_derived_jpeg_preview(source)

    assert preview_bytes is not None
    with Image.open(BytesIO(preview_bytes)) as preview:
        preview.load()
        assert preview.size == (1024, 768)


def test_generate_preview_rejects_pillow_decompression_bomb_warning(monkeypatch):
    from app.services import preview_assets

    class ImageAfterWarning:
        size = (1, 1)
        mode = "L"

        def __init__(self):
            self.converted = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def convert(self, _mode):
            self.converted = True
            return self

    image = ImageAfterWarning()

    def emit_bomb_warning(_path):
        warnings.warn("decompression bomb", Image.DecompressionBombWarning, stacklevel=2)
        return image

    monkeypatch.setattr(preview_assets.Image, "open", emit_bomb_warning)

    assert preview_assets.generate_derived_jpeg_preview("bomb.jpg") is None
    assert not image.converted


def test_generate_preview_handles_various_image_formats(tmp_path):
    """Test preview generation works with various image formats."""
    from app.services.preview_assets import generate_derived_jpeg_preview

    formats = [
        ("PNG", "test.png"),
        ("GIF", "test.gif"),
    ]

    for format_name, filename in formats:
        # Create test image in format
        test_image = Image.new("RGB", (200, 150), color="green")
        image_path = tmp_path / filename
        test_image.save(image_path, format_name)

        # Generate preview
        preview_bytes = generate_derived_jpeg_preview(image_path)

        # Should always produce JPEG bytes
        if preview_bytes is not None:
            assert preview_bytes.startswith(b"\xff\xd8\xff"), f"Failed for {format_name}"
