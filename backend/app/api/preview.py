# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authenticated preview API for indexed image documents.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Source, User
from ..services.app_settings import AppSettingsService
from ..services.search import meili_service
from .auth import ALGORITHM, get_current_user, get_secret_key

router = APIRouter(prefix="/api", tags=["preview"])

_BROWSER_IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
_RAW_IMAGE_EXTENSIONS = {"cr2", "cr3", "nef", "arw", "raf", "orf", "rw2", "dng"}
_DOWNLOAD_TOKEN_EXPIRE_SECONDS = 60
_DOWNLOAD_TOKEN_PURPOSE = "document_download"


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


@router.post("/documents/{document_id}/download-link")
async def create_document_download_link(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a short-lived signed URL for downloading an indexed document."""
    document, file_path = await _validated_indexed_file(document_id, db)
    token = _create_download_token(current_user.id, document_id)
    url = request.url_for("download_document", document_id=document_id).include_query_params(token=token)
    return {
        "url": str(url),
        "expires_in": _DOWNLOAD_TOKEN_EXPIRE_SECONDS,
        "filename": str(document.get("basename") or file_path.name),
    }


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    """Download the original file for an indexed document using a short-lived token."""
    _validate_download_token(token, document_id)
    document, file_path = await _validated_indexed_file(document_id, db)
    filename = str(document.get("basename") or file_path.name)

    return FileResponse(
        file_path,
        filename=filename,
        content_disposition_type="attachment",
    )


async def _validated_indexed_file(document_id: str, db: Session) -> tuple[dict, Path]:
    document = await meili_service.get_document(document_id)
    if document is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found")

    document = _document_to_dict(document)

    source = db.get(Source, document.get("source_id"))
    if source is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "source_not_found", "Document source not found")

    file_path = _validated_document_path(document, source)
    return document, file_path


def _create_download_token(user_id: int, document_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "doc": document_id,
        "purpose": _DOWNLOAD_TOKEN_PURPOSE,
        "iat": now,
        "exp": now + timedelta(seconds=_DOWNLOAD_TOKEN_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def _validate_download_token(token: str | None, document_id: str) -> dict[str, Any]:
    if not token:
        _preview_error(status.HTTP_401_UNAUTHORIZED, "download_token_missing", "Download token is required")

    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        _preview_error(status.HTTP_401_UNAUTHORIZED, "download_token_expired", "Download token expired")
    except jwt.InvalidTokenError:
        _preview_error(status.HTTP_401_UNAUTHORIZED, "download_token_invalid", "Invalid download token")

    if payload.get("purpose") != _DOWNLOAD_TOKEN_PURPOSE:
        _preview_error(status.HTTP_403_FORBIDDEN, "download_token_wrong_purpose", "Invalid download token purpose")
    if payload.get("doc") != document_id:
        _preview_error(status.HTTP_403_FORBIDDEN, "download_token_wrong_document", "Download token is for a different document")
    if not payload.get("sub"):
        _preview_error(status.HTTP_401_UNAUTHORIZED, "download_token_invalid", "Invalid download token")

    return payload


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
    buffer = b""
    best_jpeg: bytes | None = None
    collecting = False
    chunk_size = 64 * 1024

    with file_path.open("rb") as f:
        while bytes_read < max_bytes:
            chunk = f.read(min(chunk_size, max_bytes - bytes_read))
            if not chunk:
                break
            bytes_read += len(chunk)
            buffer += chunk

            while buffer:
                if not collecting:
                    start = buffer.find(b"\xff\xd8\xff")
                    if start == -1:
                        buffer = buffer[-2:]
                        break
                    buffer = buffer[start:]
                    collecting = True

                end = buffer.find(b"\xff\xd9", 3)
                if end == -1:
                    break

                candidate = buffer[:end + 2]
                if best_jpeg is None or len(candidate) > len(best_jpeg):
                    best_jpeg = candidate
                buffer = buffer[end + 2:]
                collecting = False

    return best_jpeg


def _preview_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})
