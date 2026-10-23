"""Durable, owner-scoped batch creation for sources."""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from ..db.database import get_db
from ..models import Agent, Source, SourceBatch, SourceBatchItem, User, _utcnow
from ..schemas import SourceBatchCreate, SourceBatchItemCreateRequest, SourceCreate
from .auth import get_current_user

router = APIRouter(prefix="/batches")
logger = logging.getLogger(__name__)
TERMINAL = {"created", "already_exists", "duplicate_selection"}


def _not_found():
    raise HTTPException(status_code=404, detail="Batch not found")


def _owned(db: Session, batch_id: str, owner_id: int) -> SourceBatch:
    batch = db.get(SourceBatch, batch_id)
    if batch is None or batch.owner_user_id != owner_id:
        _not_found()
    return batch


def _item_response(db: Session, item: SourceBatchItem) -> dict:
    earlier = db.get(SourceBatchItem, (item.batch_id, item.duplicate_of_item_id)) if item.duplicate_of_item_id else None
    source_id = item.source_id or (earlier.source_id if earlier else None)
    return {
        "id": item.item_id, "name": item.name, "root_path": item.root_path,
        "state": item.state, "source_id": source_id,
        "source_deleted": bool(source_id and db.get(Source, source_id) is None),
        "duplicate_of_item_id": item.duplicate_of_item_id, "error": item.last_error,
        "updated_at": item.updated_at,
    }


def _detail(db: Session, batch: SourceBatch) -> dict:
    return {
        "id": batch.id, "location_type": batch.location_type, "agent_id": batch.agent_id,
        "common_settings": json.loads(batch.request_snapshot).get("common_settings", {}),
        "fingerprint": batch.fingerprint, "dismissed": batch.dismissed,
        "created_at": batch.created_at, "updated_at": batch.updated_at,
        "items": [_item_response(db, item) for item in sorted(batch.items, key=lambda row: row.position)],
    }


def _summary(batch: SourceBatch) -> dict:
    counts = {"pending": 0, "created": 0, "already_exists": 0, "duplicate_selection": 0, "failed": 0}
    for item in batch.items:
        counts[item.state] += 1
    return {"id": batch.id, "created_at": batch.created_at, "updated_at": batch.updated_at,
            "fingerprint": batch.fingerprint, "dismissed": batch.dismissed, "counts": counts,
            "state": "needs_attention" if counts["failed"] else "pending" if counts["pending"] else "complete"}


@router.post("", status_code=201)
def create_batch(payload: SourceBatchCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):  # noqa: B008
    # The ASGI body limiter checks raw bytes before JSON parsing; also bound the
    # normalized snapshot persisted to the database.
    snapshot = payload.model_dump(mode="json")
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise HTTPException(status_code=413, detail="Batch request exceeds 64 KiB")
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    existing = db.get(SourceBatch, payload.id)
    if existing:
        if existing.owner_user_id != current_user.id:
            _not_found()
        if existing.fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Batch ID already has a different request")
        return _detail(db, existing)
    now = _utcnow()
    batch = SourceBatch(id=payload.id, owner_user_id=current_user.id, fingerprint=fingerprint,
                        request_snapshot=encoded, location_type=payload.location_type, agent_id=payload.agent_id,
                        created_at=now, updated_at=now)
    batch.items = [SourceBatchItem(batch_id=payload.id, item_id=item.id, position=position,
                                   name=item.name, root_path=item.root_path, created_at=now, updated_at=now)
                   for position, item in enumerate(payload.items)]
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(SourceBatch, payload.id)
        if existing and existing.owner_user_id == current_user.id and existing.fingerprint == fingerprint:
            return _detail(db, existing)
        if existing and existing.owner_user_id == current_user.id:
            raise HTTPException(status_code=409, detail="Batch ID already has a different request") from None
        _not_found()
    return _detail(db, batch)


@router.get("")
def list_batches(cursor: str | None = None, limit: int = 20, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):  # noqa: B008
    if not 1 <= limit <= 20:
        raise HTTPException(status_code=422, detail="Page size must be 1–20")
    stmt = select(SourceBatch).options(selectinload(SourceBatch.items)).where(SourceBatch.owner_user_id == current_user.id)
    if cursor:
        try:
            timestamp, batch_id = cursor.split("|", 1)
            moment = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid cursor") from error
        stmt = stmt.where(or_(SourceBatch.updated_at < moment, and_(SourceBatch.updated_at == moment, SourceBatch.id < batch_id)))
    batches = db.execute(stmt.order_by(SourceBatch.updated_at.desc(), SourceBatch.id.desc()).limit(limit + 1)).scalars().all()
    page = batches[:limit]
    next_cursor = f"{page[-1].updated_at.isoformat()}|{page[-1].id}" if len(batches) > limit else None
    return {"batches": [_summary(batch) for batch in page], "next_cursor": next_cursor}


@router.get("/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):  # noqa: B008
    return _detail(db, _owned(db, batch_id, current_user.id))


@router.post("/{batch_id}/dismiss")
def dismiss_batch(batch_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):  # noqa: B008
    batch = _owned(db, batch_id, current_user.id)
    batch.dismissed = True
    batch.updated_at = _utcnow()
    db.commit()
    return _detail(db, batch)


def _identity(location_type: str, agent_id: str | None, path: str, windows: bool) -> tuple:
    if location_type == "local":
        return ("local", os.path.realpath(os.path.expanduser(path)))
    canonical = str(PureWindowsPath(path)).casefold() if windows else str(PurePosixPath(path))
    return ("agent", agent_id, canonical)


def _preflight(db: Session, batch: SourceBatch, item: SourceBatchItem, proof: str | None):
    from .sources import (
        _build_source,
        _remote_agent,
        _require_remote_path_validation,
        _validate_source_location,
    )
    settings = json.loads(batch.request_snapshot)["common_settings"]
    path = _validate_source_location(db, location_type=batch.location_type, agent_id=batch.agent_id,
                                     processing_mode=settings.get("processing_mode"), root_path=item.root_path)
    if batch.location_type == "agent":
        _require_remote_path_validation(db, job_id=proof, agent=_remote_agent(db, batch.agent_id), root_path=path)
    source_id = "batch-" + hashlib.sha256(f"{batch.owner_user_id}:{batch.id}:{item.item_id}".encode()).hexdigest()[:40]
    data = SourceCreate(id=source_id, name=item.name, root_path=path, location_type=batch.location_type,
                        agent_id=batch.agent_id, **settings, path_validation_job_id=proof)
    return _build_source(db, data, source_id, path)


def _local_identity_without_io(path: str) -> tuple:
    # Newly created sources store a canonical absolute path. This fallback covers rows
    # inserted after the pre-lock snapshot without touching the filesystem.
    return ("local", os.path.normpath(os.path.abspath(os.path.expanduser(path))))


def _begin_immediate(db: Session):
    # Only wait briefly for the write lock. busy_timeout sticks to the pooled
    # connection, so put the old value back before anything else gets it.
    conn = db.connection()
    previous = int(conn.exec_driver_sql("PRAGMA busy_timeout").scalar())
    conn.exec_driver_sql("PRAGMA busy_timeout=400")
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    finally:
        conn.exec_driver_sql(f"PRAGMA busy_timeout={previous}")


def _write_item(db: Session, batch_id: str, item_id: str, owner_id: int, source: Source | None,
                preflight_error: str | None, proof: str | None):
    from .sources import (
        _configured_allowed_paths,
        _remote_agent,
        _require_remote_path_validation,
        _validate_source_location,
    )
    for attempt in range(3):
        try:
            # Local path checks and legacy path resolution may touch slow mounts. Do
            # them before obtaining SQLite's single writer lock on every attempt.
            db.rollback()
            local_error = preflight_error
            local_roots = None
            prior_identities = {}
            source_identities = {}
            preview = _owned(db, batch_id, owner_id)
            if preview.location_type == "local" and source and not local_error:
                preview_item = db.get(SourceBatchItem, (batch_id, item_id))
                if preview_item is None:
                    _not_found()
                try:
                    path = _validate_source_location(db, location_type="local", agent_id=None,
                        processing_mode=source.processing_mode, root_path=preview_item.root_path)
                    if path != source.root_path:
                        raise HTTPException(status_code=400, detail="Local path changed; retry this item")
                except HTTPException as exc:
                    local_error = str(exc.detail)[:500]
                local_roots = tuple(str(root) for root in _configured_allowed_paths())
                prior_identities = {
                    (row.item_id, row.root_path): _identity("local", None, row.root_path, False)
                    for row in preview.items if row.position < preview_item.position
                }
                source_identities = {
                    (row.id, row.root_path): _identity("local", None, row.root_path, False)
                    for row in db.execute(select(Source).where(Source.location_type == "local")).scalars()
                }
            db.rollback()
            _begin_immediate(db)
            batch = _owned(db, batch_id, owner_id)
            item = db.get(SourceBatchItem, (batch_id, item_id))
            if item is None:
                _not_found()
            if item.state in TERMINAL:
                result = _item_response(db, item)
                db.commit()
                return result, False
            error = local_error
            if not error:
                if batch.location_type == "local":
                    # Resolve only the bounded configured roots under the lock.
                    # The selected path and legacy source paths were resolved before
                    # it; this catches a changed root symlink at the commit boundary.
                    current_roots = tuple(str(root) for root in _configured_allowed_paths())
                    if local_roots != current_roots:
                        error = "Allowed source roots changed; retry this item"
                    elif current_roots:
                        canonical_path = source.root_path
                        allowed = []
                        for root in current_roots:
                            resolved_root = os.path.realpath(root)
                            try:
                                allowed.append(os.path.commonpath([canonical_path, resolved_root]) == resolved_root)
                            except ValueError:
                                allowed.append(False)
                        if not any(allowed):
                            error = "Root path is outside allowed directories"
                else:
                    try:
                        path = _validate_source_location(db, location_type=batch.location_type,
                            agent_id=batch.agent_id, processing_mode=source.processing_mode, root_path=item.root_path)
                        _require_remote_path_validation(db, job_id=proof,
                            agent=_remote_agent(db, batch.agent_id), root_path=path)
                    except HTTPException as exc:
                        error = str(exc.detail)[:500]
            if error:
                item.state, item.last_error = "failed", error
            else:
                agent = db.get(Agent, batch.agent_id) if batch.agent_id else None
                windows = bool(agent and agent.platform.lower().startswith("win"))
                identity = (_local_identity_without_io(source.root_path) if batch.location_type == "local" else
                            _identity(batch.location_type, batch.agent_id, source.root_path, windows))
                first = next((row for row in batch.items if row.position < item.position and
                              (prior_identities.get((row.item_id, row.root_path),
                                   _local_identity_without_io(row.root_path)) if batch.location_type == "local" else
                               _identity(batch.location_type, batch.agent_id, row.root_path, windows)) == identity), None)
                if first:
                    item.state, item.duplicate_of_item_id = "duplicate_selection", first.item_id
                    item.source_id = first.source_id
                else:
                    matches = [row for row in db.execute(select(Source).where(Source.location_type == batch.location_type,
                                Source.agent_id == batch.agent_id)).scalars()
                               if (source_identities.get((row.id, row.root_path),
                                   _local_identity_without_io(row.root_path)) if batch.location_type == "local" else
                                   _identity(row.location_type, row.agent_id, row.root_path, windows)) == identity]
                    if matches:
                        chosen = min(matches, key=lambda row: (row.created_at, row.id))
                        item.state, item.source_id = "already_exists", chosen.id
                    else:
                        if db.get(Source, source.id):
                            raise HTTPException(status_code=409, detail="Generated source ID is already used")
                        db.add(source)
                        item.state, item.source_id = "created", source.id
                item.last_error = None
            item.updated_at = batch.updated_at = _utcnow()
            db.flush()
            result = _item_response(db, item)
            db.commit()
            return result, item.state == "created"
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt == 2:
                raise HTTPException(status_code=503, detail="Database is busy; retry this item") from exc
            time.sleep(0.15 * (attempt + 1))
        except Exception:
            db.rollback()
            raise
    raise HTTPException(status_code=503, detail="Database is busy; retry this item")


@router.post("/{batch_id}/items/{item_id}/create")
def create_item(batch_id: str, item_id: str, data: SourceBatchItemCreateRequest, request: Request,
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):  # noqa: B008
    owner_id = current_user.id
    batch = _owned(db, batch_id, owner_id)
    item = db.get(SourceBatchItem, (batch_id, item_id))
    if item is None:
        _not_found()
    if item.state in TERMINAL:
        return _item_response(db, item)
    source = None
    error = None
    try:
        source = _preflight(db, batch, item, data.path_validation_job_id)
    except HTTPException as exc:
        error = str(exc.detail)[:500]
    except (OSError, ValueError):
        error = "Path or schedule is unavailable; check settings and retry"
    result, created = _write_item(db, batch_id, item_id, owner_id, source, error, data.path_validation_job_id)
    if created and hasattr(request.app.state, "scheduler"):
        try:
            request.app.state.scheduler.update_source_schedule(result["source_id"])
        except Exception:
            logger.exception("Batch source schedule registration failed for %s", result["source_id"])
            result["warning"] = "Source was created; its schedule will be reconciled on restart"
    return result
