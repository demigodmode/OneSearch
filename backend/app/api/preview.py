# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authenticated preview API for indexed image documents.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings as runtime_settings
from ..db.database import get_db
from ..models import Agent, IndexedFile, Source, User
from ..services.agent_jobs import AgentJobService, JobConflict
from ..services.app_settings import AppSettingsService
from ..services.preview_assets import (
    app_data_preview_directory,
    load_preview,
)
from ..services.remote_files import (
    RemoteFileChanged,
    RemoteFileMissing,
    RemoteStreamTimeout,
    remote_streams,
)
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
REMOTE_STREAM_FIRST_CHUNK_TIMEOUT_SECONDS = 30


@router.get("/documents/{document_id}/preview")
async def get_document_preview(
    request: Request,
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

    if source.location_type == "agent":
        indexed = _remote_indexed_file(source, document, db)
        size_bytes = indexed.size_bytes
        # Try to load stored preview first (doesn't require agent online)
        preview_base = app_data_preview_directory(runtime_settings.database_url)
        doc_path = str(document.get("path") or "")
        stored_preview = load_preview(source.id, doc_path, preview_base, modified_at_ns=indexed.modified_at_ns)
        # If we have a stored preview with matching mtime, serve it regardless of original file size
        # (stored preview is already bounded ≤2MB)
        if stored_preview is not None:
            return Response(content=stored_preview, media_type="image/jpeg")
    else:
        file_path = _validated_document_path(document, source)
        size_bytes = max(file_path.stat().st_size, int(document.get("size_bytes") or 0))
        stored_preview = None
    # Size check applies to fallback streaming path and local files
    max_bytes = app_settings.max_preview_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        _preview_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "preview_too_large",
            f"Preview file exceeds {app_settings.max_preview_size_mb} MB limit",
        )

    extension = str(
        document.get("extension") or Path(str(document.get("path") or "")).suffix.lstrip(".")
    ).lower()
    doc_type = document.get("type")

    if doc_type == "raw_image" or extension in _RAW_IMAGE_EXTENSIONS:
        if source.location_type == "agent":
            _preview_error(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "raw_preview_unavailable",
                "RAW embedded preview is not available for remote files",
            )
        if not app_settings.raw_preview_enabled:
            _preview_error(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "raw_preview_disabled",
                "RAW previews are disabled",
            )
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

    if source.location_type == "agent":
        # Fall back to streaming from agent
        _require_available_remote_source(source, db)
        return await _remote_file_response(
            request=request,
            source=source,
            document=document,
            size_bytes=indexed.size_bytes,
            modified_at=indexed.modified_at_ns,
            media_type=media_type,
            filename=None,
            db=db,
        )

    return FileResponse(file_path, media_type=media_type, filename=file_path.name)


@router.post("/documents/{document_id}/download-link")
async def create_document_download_link(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a short-lived signed URL for downloading an indexed document."""
    document = _document_to_dict(await meili_service.get_document(document_id))
    if not document:
        _preview_error(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found")
    source = db.get(Source, document.get("source_id"))
    if source is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "source_not_found", "Document source not found")
    if source.location_type == "agent":
        _require_available_remote_source(source, db)
    file_path = (
        None if source.location_type == "agent" else _validated_document_path(document, source)
    )
    token = _create_download_token(current_user.id, document_id)
    url = f"/api/documents/{quote(document_id, safe='')}/download?{urlencode({'token': token})}"
    return {
        "url": url,
        "expires_in": _DOWNLOAD_TOKEN_EXPIRE_SECONDS,
        "filename": str(document.get("basename") or (file_path.name if file_path else "download")),
    }


@router.get("/documents/{document_id}/download")
async def download_document(
    request: Request,
    document_id: str,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    """Download the original file for an indexed document using a short-lived token."""
    _validate_download_token(token, document_id)
    document = _document_to_dict(await meili_service.get_document(document_id))
    if not document:
        _preview_error(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found")
    source = db.get(Source, document.get("source_id"))
    if source is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "source_not_found", "Document source not found")
    if source.location_type == "agent":
        _require_available_remote_source(source, db)
        indexed = _remote_indexed_file(source, document, db)
        return await _remote_file_response(
            request=request,
            source=source,
            document=document,
            size_bytes=indexed.size_bytes,
            modified_at=indexed.modified_at_ns,
            media_type="application/octet-stream",
            filename=str(document.get("basename") or "download"),
            db=db,
        )
    file_path = _validated_document_path(document, source)
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


def _require_available_remote_source(source: Source, db: Session) -> Agent:
    from ..services.agent_auth import agent_is_fresh, mark_stale_agent_offline

    enabled = AppSettingsService(db).get_settings().remote_agents_enabled
    agent = db.get(Agent, source.agent_id) if source.agent_id else None
    if agent is not None and agent.status == "online" and not agent_is_fresh(agent):
        mark_stale_agent_offline(db, agent)
        db.commit()
        db.expire(agent)
        agent = db.get(Agent, agent.id)
    if not enabled or agent is None or agent.status != "online" or agent.approved_at is None:
        _preview_error(status.HTTP_409_CONFLICT, "agent_offline", "Remote agent is unavailable")
    return agent


def _remote_indexed_file(source: Source, document: dict, db: Session) -> IndexedFile:
    path = str(document.get("path") or "")
    indexed = (
        db.query(IndexedFile)
        .filter(IndexedFile.source_id == source.id, IndexedFile.path == path)
        .one_or_none()
    )
    if indexed is None:
        _preview_error(status.HTTP_404_NOT_FOUND, "remote_file_missing", "Remote file is missing")
    if indexed.status != "success" or indexed.size_bytes is None or indexed.modified_at_ns is None:
        _preview_error(status.HTTP_409_CONFLICT, "remote_file_changed", "Remote file changed")
    return indexed


async def _stream_remote_body(request: Request, db: Session, job, queue):
    eof = False
    try:
        while True:
            if await request.is_disconnected():
                return
            try:
                item = await asyncio.wait_for(
                    queue.get(), timeout=REMOTE_STREAM_FIRST_CHUNK_TIMEOUT_SECONDS
                )
            except TimeoutError as error:
                raise RemoteStreamTimeout("agent did not stream in time") from error
            if item is None:
                eof = True
                return
            yield item
    except asyncio.CancelledError:
        raise
    finally:
        if not eof:
            try:
                AgentJobService(db).cancel(job.id)
                db.commit()
            except JobConflict:
                pass
        await remote_streams.close(job.id)


async def _remote_file_response(
    *,
    request: Request,
    source: Source,
    document: dict,
    size_bytes: int,
    modified_at: int,
    media_type: str,
    filename: str | None,
    db: Session,
):
    job = None
    try:
        job = AgentJobService(db).enqueue_stream_file(
            source,
            path=str(document.get("path") or ""),
            size_bytes=size_bytes,
            modified_at=modified_at,
        )
        queue = remote_streams.open(job.id, expected_size=size_bytes)
        db.commit()
        body = _stream_remote_body(request, db, job, queue)
        try:
            first = await anext(body)
        except StopAsyncIteration:
            return Response(content=b"", media_type=media_type, headers=_remote_headers(filename))
        except RemoteStreamTimeout as error:
            _preview_error(status.HTTP_504_GATEWAY_TIMEOUT, error.code, str(error))
        except RemoteFileMissing as error:
            _preview_error(status.HTTP_404_NOT_FOUND, error.code, str(error))
        except RemoteFileChanged as error:
            _preview_error(status.HTTP_409_CONFLICT, error.code, str(error))

        async def stream():
            try:
                yield first
                async for item in body:
                    yield item
            finally:
                await body.aclose()

        return StreamingResponse(stream(), media_type=media_type, headers=_remote_headers(filename))
    except JobConflict:
        db.rollback()
        if job is not None:
            await remote_streams.close(job.id)
        _preview_error(status.HTTP_409_CONFLICT, "agent_offline", "Remote agent is unavailable")
    except Exception:
        db.rollback()
        if job is not None:
            await remote_streams.close(job.id)
        raise


def _remote_headers(filename: str | None) -> dict[str, str]:
    if filename is None:
        return {}
    safe_filename = filename.replace("\r", "").replace("\n", "")
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_filename, safe='')}"}


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
        _preview_error(
            status.HTTP_401_UNAUTHORIZED, "download_token_missing", "Download token is required"
        )

    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        _preview_error(
            status.HTTP_401_UNAUTHORIZED, "download_token_expired", "Download token expired"
        )
    except jwt.InvalidTokenError:
        _preview_error(
            status.HTTP_401_UNAUTHORIZED, "download_token_invalid", "Invalid download token"
        )

    if payload.get("purpose") != _DOWNLOAD_TOKEN_PURPOSE:
        _preview_error(
            status.HTTP_403_FORBIDDEN,
            "download_token_wrong_purpose",
            "Invalid download token purpose",
        )
    if payload.get("doc") != document_id:
        _preview_error(
            status.HTTP_403_FORBIDDEN,
            "download_token_wrong_document",
            "Download token is for a different document",
        )
    if not payload.get("sub"):
        _preview_error(
            status.HTTP_401_UNAUTHORIZED, "download_token_invalid", "Invalid download token"
        )

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

                candidate = buffer[: end + 2]
                if best_jpeg is None or len(candidate) > len(best_jpeg):
                    best_jpeg = candidate
                buffer = buffer[end + 2 :]
                collecting = False

    return best_jpeg


def _preview_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})
