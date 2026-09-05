# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent worker preview generation."""

import asyncio
import stat
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from onesearch_shared import (
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
    AllowedRoot,
    BatchAck,
    JobKind,
    ProcessingMode,
    ScanCheckpoint,
    ScanFile,
    ScanManifestPageAck,
    ScanPageOutcomeAck,
    remote_path_hash,
)
from PIL import Image

from app.services.preview_assets import generate_derived_jpeg_preview


def test_generate_preview_from_real_jpg_image(tmp_path):
    """Test preview generation from a real JPEG image."""
    image_path = tmp_path / "test.jpg"
    test_image = Image.new("RGB", (800, 600), color="blue")
    test_image.save(image_path, "JPEG")

    preview_bytes = generate_derived_jpeg_preview(image_path)

    assert preview_bytes is not None
    assert len(preview_bytes) > 0
    assert preview_bytes.startswith(b"\xff\xd8\xff")  # JPEG magic
    assert len(preview_bytes) <= 2 * 1024 * 1024  # Bounded by 2MB


def test_generate_preview_handles_corrupt_image(tmp_path):
    """Test that corrupt images return None gracefully."""
    corrupt_path = tmp_path / "corrupt.jpg"
    corrupt_path.write_bytes(b"not a valid jpeg at all")

    preview_bytes = generate_derived_jpeg_preview(corrupt_path)

    assert preview_bytes is None


def test_generate_preview_skips_non_displayable_formats(tmp_path):
    """Test that preview generation works for displayable formats (PNG, GIF, etc)."""
    # Test PNG
    png_path = tmp_path / "test.png"
    test_image = Image.new("RGB", (400, 300), color="green")
    test_image.save(png_path, "PNG")

    preview_bytes = generate_derived_jpeg_preview(png_path)
    assert preview_bytes is not None
    assert preview_bytes.startswith(b"\xff\xd8\xff")


@pytest.mark.asyncio
async def test_maybe_upload_preview_filters_by_extension():
    """Test that _maybe_upload_preview only processes displayable formats."""
    from onesearch_agent.worker import _maybe_upload_preview

    mock_client = AsyncMock()
    mock_client.upload_preview = AsyncMock()

    mock_lease = Mock()
    mock_lease.id = "job-123"
    mock_lease.lease_token = "token-123"

    # Test with non-displayable format
    await _maybe_upload_preview(
        mock_client,
        mock_lease,
        "document.pdf",
        1_000_000_000_000_000_000,
        "/path/to/document.pdf",
        mutation_attempts=1,
        sleep=asyncio.sleep,
    )

    # Should not call upload_preview for PDF
    assert not mock_client.upload_preview.called


@pytest.mark.asyncio
async def test_maybe_upload_preview_calls_with_correct_params(tmp_path):
    """Test that _maybe_upload_preview calls upload_preview with correct params."""
    from onesearch_agent.worker import _maybe_upload_preview

    # Create a test image
    image_path = tmp_path / "photo.jpg"
    test_image = Image.new("RGB", (200, 150), color="red")
    test_image.save(image_path, "JPEG")

    mock_client = AsyncMock()
    mock_client.upload_preview = AsyncMock()

    mock_lease = Mock()
    mock_lease.id = "job-456"
    mock_lease.lease_token = "token-456"

    mtime_ns = 1_700_000_000_000_000_000
    path = "photos/photo.jpg"

    # Mock _submit_idempotent to not actually call the client
    original_submit = None
    try:
        from onesearch_agent import worker
        original_submit = worker._submit_idempotent

        async def mock_submit(operation, **kwargs):
            # Just execute the operation but don't retry
            return await operation()

        worker._submit_idempotent = mock_submit

        await _maybe_upload_preview(
            mock_client,
            mock_lease,
            path,
            mtime_ns,
            str(image_path),
            mutation_attempts=1,
            sleep=asyncio.sleep,
        )

        # Verify upload_preview was called
        assert mock_client.upload_preview.called
        call_kwargs = mock_client.upload_preview.call_args[0]
        # First three positional args are lease.id, lease.lease_token, then kwargs
        assert call_kwargs[0] == mock_lease.id
        assert call_kwargs[1] == mock_lease.lease_token
    finally:
        if original_submit:
            worker._submit_idempotent = original_submit


@pytest.mark.asyncio
async def test_confined_preview_stops_copy_before_snapshot_limit(monkeypatch):
    """A growing read cannot write past the v3 snapshot cap or upload a preview."""
    from onesearch_agent import worker

    class GrowingReader:
        def __init__(self):
            self.chunks = iter((b"abc", b"def"))

        def fileno(self):
            return 1

        def read(self, _size):
            return next(self.chunks, b"")

    @contextmanager
    def open_growing_file(*_args, **_kwargs):
        yield GrowingReader()

    written, preview_calls = [], []

    @contextmanager
    def record_snapshot_write(_path, _mode):
        class Output:
            def write(self, data):
                written.append(data)

        yield Output()

    async def record_preview(*_args, **_kwargs):
        preview_calls.append(True)

    monkeypatch.setattr(worker, "open_confined_file", open_growing_file)
    monkeypatch.setattr(
        worker.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=4, st_mtime_ns=1),
    )
    monkeypatch.setattr(worker.Path, "open", record_snapshot_write)
    monkeypatch.setattr(worker, "_maybe_upload_preview", record_preview)

    await worker._maybe_upload_confined_preview(
        SimpleNamespace(),
        SimpleNamespace(),
        "nested/photo.jpg",
        ScanFile(
            path="nested/photo.jpg",
            path_hash=remote_path_hash("nested/photo.jpg"),
            size_bytes=4,
            modified_at=1,
        ),
        root_id="root-id",
        roots=[],
        source_prefix="source_prefix",
        max_snapshot_bytes=4,
    )

    assert written == [b"abc"]
    assert preview_calls == []


@pytest.mark.asyncio
async def test_v3_on_agent_scan_uploads_preview_from_confined_source_path(tmp_path):
    """A source-relative protocol path must not be reopened from the process CWD."""
    from onesearch_agent import worker

    source = tmp_path / "source_prefix"
    image_path = source / "nested" / "photo.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (200, 150), color="purple").save(image_path, "JPEG")

    lease = SimpleNamespace(
        id="preview-job",
        lease_token="preview-token",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="source-id",
        payload={
            "protocol_version": 3,
            "full": True,
            "root_id": "root-id",
            "root_path": str(source),
            "include_patterns": None,
            "exclude_patterns": None,
            "extraction": {
                "source_name": "source",
                "unsupported_file_policy": "metadata_only",
                "media_metadata_mode": "auto",
                "raw_metadata_mode": "auto",
                "index_gps_metadata": False,
                "max_text_file_size_mb": 10,
                "max_pdf_file_size_mb": 50,
                "max_office_file_size_mb": 50,
                "image_metadata_max_size_mb": 100,
                "epub_extraction_max_size_mb": 100,
                "comic_extraction_max_size_mb": 100,
                "media_probe_max_size_mb": 0,
                "text_extraction_timeout": 5,
                "pdf_extraction_timeout": 30,
                "office_extraction_timeout": 30,
                "raw_metadata_timeout_seconds": 10,
            },
            "limits": {
                "max_snapshot_bytes": 1024 * 1024,
                "max_batch_documents": 10,
                "max_batch_bytes": 100_000,
                "max_entries_per_directory": 10,
                "max_manifest_page_entries": REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
                "max_manifest_page_bytes": REMOTE_MAX_MANIFEST_PAGE_BYTES,
            },
        },
    )

    class Client:
        def __init__(self):
            self.pages, self.batches, self.previews = [], [], []

        async def job_heartbeat(self, *_args):
            pass

        async def submit_manifest_page(self, _job_id, page, _token):
            self.pages.append(page)
            return ScanManifestPageAck(
                job_id=lease.id,
                sequence=page.page.sequence,
                checksum=page.checksum,
                accepted_count=len(page.page.files),
                changed_paths=["nested/photo.jpg"],
                checkpoint=page.page.checkpoint,
            )

        async def submit_batch(self, _job_id, batch, _token):
            self.batches.append(batch)
            return BatchAck(batch_id=batch.batch_id, accepted_count=len(batch.documents))

        async def submit_page_outcome(self, _job_id, outcome, _token):
            return ScanPageOutcomeAck(
                job_id=lease.id,
                sequence=outcome.outcome.sequence,
                checksum=outcome.checksum,
                settled_count=len(outcome.outcome.results),
                checkpoint=ScanCheckpoint(cursor="page:0", scanned_count=1),
            )

        async def upload_preview(self, _job_id, _token, **kwargs):
            self.previews.append(kwargs)

        async def complete(self, *_args):
            pass

    client = Client()
    await worker.run_scan_job(
        lease,
        client,
        roots=[AllowedRoot(root_id="root-id", path=str(tmp_path))],
        state_dir=tmp_path / "state",
    )

    assert [file.path for page in client.pages for file in page.page.files] == ["nested/photo.jpg"]
    assert [document.path for batch in client.batches for document in batch.documents] == [
        "nested/photo.jpg"
    ]
    assert [preview["path"] for preview in client.previews] == ["nested/photo.jpg"]
    with Image.open(BytesIO(client.previews[0]["preview_bytes"])) as preview:
        assert preview.format == "JPEG"
        preview.load()
        assert preview.size == (200, 150)
