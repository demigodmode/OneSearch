# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Derived preview asset generation and storage for remote documents."""

from pathlib import Path

from PIL import Image


def app_data_preview_directory(database_url: str) -> Path:
    """Get the directory for storing derived previews, colocated with database."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return Path(database_url.removeprefix(prefix)).parent / "previews"
    return Path("/app/data/previews")


def _is_browser_displayable_image(extension: str) -> bool:
    """Check if extension is a browser-displayable image type."""
    return extension.lower() in {"jpg", "jpeg", "png", "webp", "gif"}


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
        image = Image.open(source_path)
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

        # Save as JPEG with quality cap
        jpeg_buffer = bytearray()
        image.save(
            jpeg_buffer, format="JPEG", quality=quality, optimize=False
        )  # optimize=False for speed

        if len(jpeg_buffer) <= max_bytes:
            return bytes(jpeg_buffer)
        return None
    except Exception:
        # Corrupt or unsupported images don't fail the scan
        return None


def store_preview(source_id: str, path: str, preview_bytes: bytes, base_dir: Path) -> Path | None:
    """
    Store a derived preview on disk.

    Returns the path to the stored preview file, or None if storage failed.
    """
    try:
        from onesearch_shared import remote_path_hash

        source_dir = base_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        path_hash = remote_path_hash(path)
        preview_file = source_dir / f"{path_hash}.jpg"

        # Atomic write: write to temp file then rename
        temp_file = preview_file.with_suffix(".tmp")
        temp_file.write_bytes(preview_bytes)
        temp_file.replace(preview_file)

        return preview_file
    except Exception:
        return None


def load_preview(source_id: str, path: str, base_dir: Path) -> bytes | None:
    """Load a stored derived preview from disk."""
    try:
        from onesearch_shared import remote_path_hash

        source_dir = base_dir / source_id
        path_hash = remote_path_hash(path)
        preview_file = source_dir / f"{path_hash}.jpg"

        if preview_file.exists():
            return preview_file.read_bytes()
    except Exception:
        pass
    return None


def delete_preview(source_id: str, path: str, base_dir: Path) -> None:
    """Delete a stored derived preview."""
    try:
        from onesearch_shared import remote_path_hash

        source_dir = base_dir / source_id
        path_hash = remote_path_hash(path)
        preview_file = source_dir / f"{path_hash}.jpg"
        preview_file.unlink(missing_ok=True)
    except Exception:
        pass


def delete_source_previews(source_id: str, base_dir: Path) -> None:
    """Delete all previews for a source."""
    try:
        source_dir = base_dir / source_id
        if source_dir.exists():
            import shutil

            shutil.rmtree(source_dir, ignore_errors=True)
    except Exception:
        pass
