# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Derived preview asset generation and storage for remote documents."""

import glob
import shutil
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from onesearch_shared import remote_path_hash
from PIL import Image


def app_data_preview_directory(database_url: str) -> Path:
    """Get the directory for storing derived previews, colocated with database."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return Path(database_url.removeprefix(prefix)).parent / "previews"
    return Path("/app/data/previews")


BROWSER_DISPLAYABLE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}


def is_browser_displayable_image(extension: str) -> bool:
    """Check if extension is a browser-displayable image type."""
    return extension.lower() in BROWSER_DISPLAYABLE_IMAGE_EXTENSIONS


def generate_derived_jpeg_preview(
    source_path: str | Path,
    *,
    max_dimension: int = 1024,
    quality: int = 80,
    max_bytes: int = 2 * 1024 * 1024,
) -> bytes | None:
    """
    Generate a bounded derived JPEG preview from a source image.

    Returns the JPEG bytes if successful, None if the image cannot be read
    or the derived preview would exceed max_bytes.

    Corrupt or undecodable images do not raise an exception.
    """
    try:
        with Image.open(source_path) as image:
            # Animated GIFs: use first frame which is already loaded in PIL
            # Ensure RGB
            if image.mode in {"RGBA", "LA", "P"}:
                rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                rgb_image.paste(image, mask=image.split()[-1] if image.mode in {"RGBA", "LA"} else None)
                image = rgb_image
            elif image.mode != "RGB":
                image = image.convert("RGB")

            # Scale down if needed
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            # Save as JPEG to BytesIO with quality cap
            jpeg_buffer = BytesIO()
            image.save(jpeg_buffer, format="JPEG", quality=quality, optimize=False)

            preview_bytes = jpeg_buffer.getvalue()
            if len(preview_bytes) <= max_bytes:
                return preview_bytes
        return None
    except Exception:
        # Corrupt or unsupported images don't fail the scan
        return None


def store_preview(source_id: str, path: str, preview_bytes: bytes, base_dir: Path, modified_at_ns: int) -> Path | None:
    """
    Store a derived preview on disk, keyed by path and mtime.

    Preview is stored as {path_hash}-{modified_at_ns}.jpg.
    Old variants with different mtimes are cleaned up.

    Returns the path to the stored preview file, or None if storage failed.
    """
    try:
        source_dir = base_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        path_hash = remote_path_hash(path)
        preview_file = source_dir / f"{path_hash}-{modified_at_ns}.jpg"

        # Clean up old variants with different mtimes
        for old_file in glob.glob(str(source_dir / f"{path_hash}-*.jpg")):
            old_path = Path(old_file)
            if old_path != preview_file:
                with suppress(Exception):
                    old_path.unlink()

        # Atomic write: write to temp file then rename
        temp_file = preview_file.with_suffix(".tmp")
        temp_file.write_bytes(preview_bytes)
        temp_file.replace(preview_file)

        return preview_file
    except Exception:
        return None


def load_preview(source_id: str, path: str, base_dir: Path, modified_at_ns: int) -> bytes | None:
    """Load a stored derived preview from disk, matching the provided mtime."""
    try:
        source_dir = base_dir / source_id
        path_hash = remote_path_hash(path)
        preview_file = source_dir / f"{path_hash}-{modified_at_ns}.jpg"

        if preview_file.exists():
            return preview_file.read_bytes()
    except Exception:
        pass
    return None


def delete_preview(source_id: str, path: str, base_dir: Path) -> None:
    """Delete stored derived previews, including all mtime variants."""
    try:
        source_dir = base_dir / source_id
        path_hash = remote_path_hash(path)

        # Delete all {path_hash}-*.jpg variants
        for file_path in glob.glob(str(source_dir / f"{path_hash}-*.jpg")):
            with suppress(Exception):
                Path(file_path).unlink()
    except Exception:
        pass


def delete_source_previews(source_id: str, base_dir: Path) -> None:
    """Delete all previews for a source."""
    try:
        source_dir = base_dir / source_id
        if source_dir.exists():
            shutil.rmtree(source_dir, ignore_errors=True)
    except Exception:
        pass
