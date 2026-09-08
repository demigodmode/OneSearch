# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Derived preview asset generation and storage for remote documents."""

import glob
import shutil
import threading
import uuid
import warnings
from contextlib import contextmanager, suppress
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
# Preview generation can otherwise decode a small compressed image into a very large bitmap.
# 16 megapixels bounds an RGB source image to roughly 46 MiB before thumbnailing.
MAX_PREVIEW_PIXELS = 16_000_000


class PreviewKeyLockRegistry:
    """Reference-counted locks that disappear after the last holder or waiter exits."""

    def __init__(self):
        self._entries: dict[str, tuple[threading.Lock, int]] = {}
        self._guard = threading.Lock()

    @property
    def active_key_count(self) -> int:
        with self._guard:
            return len(self._entries)

    def references_for(self, key: str) -> int:
        with self._guard:
            entry = self._entries.get(key)
            return entry[1] if entry else 0

    @contextmanager
    def hold(self, key: str):
        with self._guard:
            lock, references = self._entries.get(key, (threading.Lock(), 0))
            self._entries[key] = (lock, references + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                current_lock, references = self._entries[key]
                if references == 1:
                    del self._entries[key]
                else:
                    self._entries[key] = (current_lock, references - 1)


preview_key_locks = PreviewKeyLockRegistry()


def is_browser_displayable_image(extension: str) -> bool:
    """Check if extension is a browser-displayable image type."""
    return extension.lower() in BROWSER_DISPLAYABLE_IMAGE_EXTENSIONS


def is_valid_derived_jpeg(preview_bytes: bytes) -> bool:
    """Return whether bounded bytes decode as a non-bomb JPEG preview."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(preview_bytes)) as image:
                if image.format != "JPEG" or image.width * image.height > MAX_PREVIEW_PIXELS:
                    return False
                image.verify()
            # ``verify`` checks structure; reopening and loading forces a complete decode.
            with Image.open(BytesIO(preview_bytes)) as image:
                if image.format != "JPEG" or image.width * image.height > MAX_PREVIEW_PIXELS:
                    return False
                image.load()
        return True
    except Exception:
        return False


def _remove_stale_preview_variants(preview_file: Path) -> None:
    for old_file in glob.glob(str(preview_file.parent / f"{preview_file.stem.split('-')[0]}-*.jpg")):
        old_path = Path(old_file)
        if old_path != preview_file:
            with suppress(Exception):
                old_path.unlink()


def _atomic_write_preview(preview_file: Path, preview_bytes: bytes) -> None:
    temp_file = preview_file.with_name(f".{preview_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_file.write_bytes(preview_bytes)
        temp_file.replace(preview_file)
    finally:
        with suppress(FileNotFoundError):
            temp_file.unlink()


def store_preview_if_absent_or_identical(
    source_id: str, path: str, preview_bytes: bytes, base_dir: Path, modified_at_ns: int
) -> bool | None:
    """Atomically create one preview key, accepting only byte-identical retries.

    True means stored or an identical preview already existed; False is a conflict;
    None is a storage failure.
    """
    try:
        source_dir = base_dir / source_id
        preview_file = source_dir / f"{remote_path_hash(path)}-{modified_at_ns}.jpg"
        with preview_key_locks.hold(str(preview_file)):
            source_dir.mkdir(parents=True, exist_ok=True)
            if preview_file.exists():
                return preview_file.read_bytes() == preview_bytes
            _atomic_write_preview(preview_file, preview_bytes)
            _remove_stale_preview_variants(preview_file)
            return True
    except Exception:
        return None


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
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_path) as image:
                if image.width * image.height > MAX_PREVIEW_PIXELS:
                    return None
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

        with preview_key_locks.hold(str(preview_file)):
            _atomic_write_preview(preview_file, preview_bytes)
            _remove_stale_preview_variants(preview_file)

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
