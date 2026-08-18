# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent worker preview generation."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
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
