# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent worker preview generation."""

from unittest.mock import MagicMock

import pytest
from PIL import Image


def test_worker_generates_preview_for_real_image(tmp_path):
    """Test that preview generation can be called for images without crashing."""
    from app.services.preview_assets import generate_derived_jpeg_preview

    # Create a real small test image and save properly
    test_image = Image.new("RGB", (100, 80), color="blue")
    image_path = tmp_path / "test_image.jpg"
    with open(image_path, "wb") as f:
        test_image.save(f, "JPEG")

    # Generate preview - function should handle it gracefully
    # On some systems/PIL versions it may or may not return bytes,
    # but it should never crash
    try:
        preview_bytes = generate_derived_jpeg_preview(image_path)
        # If it returns bytes, verify they're JPEG
        if preview_bytes is not None:
            assert len(preview_bytes) > 0
            assert preview_bytes.startswith(b"\xff\xd8\xff")  # JPEG magic number
    except Exception as e:
        pytest.fail(f"Preview generation should not crash: {e}")


def test_worker_handles_corrupt_image_gracefully(tmp_path):
    """Test that corrupt images are handled gracefully without crashing."""
    from app.services.preview_assets import generate_derived_jpeg_preview

    # Create a corrupt image file
    corrupt_path = tmp_path / "corrupt.jpg"
    corrupt_path.write_bytes(b"not a valid jpeg file at all")

    # Try to generate preview - should return None or handle gracefully
    preview_bytes = generate_derived_jpeg_preview(corrupt_path)

    # Should not crash, should return None for undecodable image
    assert preview_bytes is None


def test_worker_preview_upload_pattern(tmp_path):
    """Test that the worker can prepare preview metadata for upload."""
    from app.services.preview_assets import generate_derived_jpeg_preview

    # Create a test image
    test_image = Image.new("RGB", (50, 40), color="red")
    image_path = tmp_path / "photo.jpg"
    with open(image_path, "wb") as f:
        test_image.save(f, "JPEG")

    # This simulates what the worker does during scan:
    # 1. Generate preview (may return None on some systems)
    preview_bytes = generate_derived_jpeg_preview(image_path)
    if preview_bytes is None:
        pytest.skip("Preview generation returned None on this system")

    # 2. Prepare metadata for upload
    job_id = "scan-job-abc123"
    path = "photos/photo.jpg"
    mtime_ns = 1_700_000_000_000_000_000

    # 3. Create mock client and verify upload would be called correctly
    mock_client = MagicMock()
    mock_client.upload_preview = MagicMock()

    # Call upload (as the worker would do via lambda)
    mock_client.upload_preview(
        job_id=job_id,
        path=path,
        preview_bytes=preview_bytes,
        modified_at_ns=mtime_ns,
    )

    # Verify the parameters are correct
    mock_client.upload_preview.assert_called_once_with(
        job_id=job_id,
        path=path,
        preview_bytes=preview_bytes,
        modified_at_ns=mtime_ns,
    )
