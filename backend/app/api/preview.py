# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authenticated preview API for indexed image documents.
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Source, User
from ..services.app_settings import AppSettingsService
from ..services.search import meili_service
from .auth import get_current_user

router = APIRouter(prefix="/api", tags=["preview"])

_BROWSER_IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
_RAW_IMAGE_EXTENSIONS = {"cr2", "cr3", "nef", "arw", "raf", "orf", "rw2", "dng"}


@router.get("/documents/{document_id}/preview")
async def get_document_preview(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream a safe preview for an indexed image document."""
    app_settings = AppSettingsService(db).get_settings()
    if not app_settings.show_previews:
        _preview_error(status.HTTP_403_FORBIDDEN, "previews_disabled", "Previews are disabled")

    document = await meili_service.get_document(document_id)
    if document is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found")

    document = _document_to_dict(document)

    source = db.get(Source, document.get("source_id"))
    if source is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "source_not_found", "Document source not found")

    file_path = _validated_document_path(document, source)
    size_bytes = max(file_path.stat().st_size, int(document.get("size_bytes") or 0))
    max_bytes = app_settings.max_preview_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        _preview_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "preview_too_large",
            f"Preview file exceeds {app_settings.max_preview_size_mb} MB limit",
        )

    extension = str(document.get("extension") or file_path.suffix.lower().lstrip(".")).lower()
    doc_type = document.get("type")

    if doc_type == "raw_image" or extension in _RAW_IMAGE_EXTENSIONS:
        if not app_settings.raw_preview_enabled:
            _preview_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "raw_preview_disabled", "RAW previews are disabled")
        embedded_jpeg = await asyncio.to_thread(_extract_embedded_jpeg, file_path, max_bytes)
        if embedded_jpeg is None:
            _preview_error(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "raw_preview_unavailable",
                "RAW embedded preview is not available for this file",
            )
        return Response(content=embedded_jpeg, media_type="image/jpeg")

    media_type = _BROWSER_IMAGE_TYPES.get(extension)
    if doc_type != "image" or media_type is None:
        _preview_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_preview_type",
            "Preview is not supported for this document type",
        )

    return FileResponse(file_path, media_type=media_type, filename=file_path.name)


def _document_to_dict(document) -> dict:
    if isinstance(document, dict):
        return document
    try:
        return dict(document)
    except (TypeError, ValueError):
        return dict(getattr(document, "__dict__", {}))


def _validated_document_path(document: dict, source: Source) -> Path:
    raw_path = document.get("path")
    if not raw_path:
        _preview_error(status.HTTP_400_BAD_REQUEST, "missing_path", "Document has no file path")

    file_path = Path(raw_path).resolve()
    source_root = Path(source.root_path).resolve()
    if file_path != source_root and source_root not in file_path.parents:
        _preview_error(
            status.HTTP_403_FORBIDDEN,
            "path_outside_source",
            "Document path is outside its configured source",
        )

    if not file_path.exists():
        _preview_error(status.HTTP_404_NOT_FOUND, "file_not_found", "Indexed file no longer exists")
    if not file_path.is_file():
        _preview_error(status.HTTP_400_BAD_REQUEST, "not_a_file", "Indexed path is not a file")

    return file_path


def _extract_embedded_jpeg(file_path: Path, max_bytes: int) -> bytes | None:
    bytes_read = 0
    searching_tail = b""
    jpeg_data: bytearray | None = None
    chunk_size = 64 * 1024

    with file_path.open("rb") as f:
        while bytes_read < max_bytes:
            chunk = f.read(min(chunk_size, max_bytes - bytes_read))
            if not chunk:
                break
            bytes_read += len(chunk)

            if jpeg_data is None:
                window = searching_tail + chunk
                start = window.find(b"\xff\xd8\xff")
                if start == -1:
                    searching_tail = window[-2:]
                    continue
                jpeg_data = bytearray(window[start:])
                search_from = 0
            else:
                search_from = max(0, len(jpeg_data) - 1)
                jpeg_data.extend(chunk)

            end = jpeg_data.find(b"\xff\xd9", search_from)
            if end != -1:
                return bytes(jpeg_data[:end + 2])

    return None


def _preview_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})
