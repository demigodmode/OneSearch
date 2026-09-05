# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Source management API endpoints
Provides CRUD operations for search sources
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from onesearch_shared import BrowseResult
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.database import get_db
from ..models import Agent, AgentJob, IndexedFile, Source, User
from ..schemas import (
    ScheduleConfig,
    SourceBrowseRequest,
    SourceBrowseResponse,
    SourceCreate,
    SourcePathTestRequest,
    SourcePathTestResponse,
    SourceResponse,
    SourceUpdate,
)
from ..services.agent_jobs import AgentJobService, JobConflict
from ..services.app_settings import AppSettingsService
from ..services.indexer import IndexingService
from ..services.scan_dispatcher import (
    AgentUnavailableError,
    RemoteAgentsDisabledError,
    ScanDispatcher,
)
from ..services.scanner import FileScanner
from ..services.scheduler import (
    calculate_next_run_time_for_schedule,
    get_source_lock,
    resolve_effective_schedule,
    validate_interval,
    validate_schedule,
)
from ..services.search import meili_service
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])

# A remote path may change between validation and source creation. Keep the proof
# short-lived without consuming it; current administration is single-user.
REMOTE_PATH_VALIDATION_MAX_AGE = timedelta(minutes=10)


def _configured_allowed_paths() -> list[Path]:
    return [
        Path(p.strip()).expanduser() for p in settings.allowed_source_paths.split(",") if p.strip()
    ]


def _is_within_path(path: Path, parent: Path) -> bool:
    try:
        path_abs = os.path.abspath(os.path.expanduser(os.fspath(path)))
        parent_abs = os.path.abspath(os.path.expanduser(os.fspath(parent)))
        return os.path.commonpath([path_abs, parent_abs]) == parent_abs
    except (OSError, ValueError):
        return False


def _display_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _allowed_roots_hint(allowed: list[Path]) -> str | None:
    if not allowed:
        return None
    return "Allowed source roots: " + ", ".join(_display_path(path) for path in allowed)


def _looks_like_windows_host_path(path_text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path_text)) or "\\" in path_text


def _looks_like_linux_host_path(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/")
    host_prefixes = ("/mnt/", "/media/", "/home/", "/Users/", "/Volumes/")
    return normalized.startswith(host_prefixes)


def build_source_path_test_response(root_path: str) -> SourcePathTestResponse:
    """Return source path diagnostics without creating or updating a source."""
    raw_path = str(root_path).strip()
    allowed = _configured_allowed_paths()
    allowed_roots = [_display_path(path) for path in allowed]
    hint = _allowed_roots_hint(allowed)
    looks_like_host_path = _looks_like_windows_host_path(raw_path)

    if not raw_path:
        return SourcePathTestResponse(
            path=raw_path,
            ok=False,
            exists=False,
            is_directory=False,
            readable=False,
            inside_allowed_roots=False,
            allowed_roots=allowed_roots,
            looks_like_host_path=False,
            message="Root path is required.",
            hint=hint,
        )

    path = Path(raw_path)

    if allowed and not any(_is_within_path(path, allowed_path) for allowed_path in allowed):
        looks_like_host_path = looks_like_host_path or _looks_like_linux_host_path(raw_path)
        message = "Root path is outside allowed source roots."
        if _looks_like_windows_host_path(raw_path):
            message = "This looks like a host path. OneSearch can only see container paths mounted into the container."
        return SourcePathTestResponse(
            path=raw_path,
            ok=False,
            exists=False,
            is_directory=False,
            readable=False,
            inside_allowed_roots=False,
            allowed_roots=allowed_roots,
            looks_like_host_path=looks_like_host_path,
            message=message,
            hint=hint,
        )

    resolved = Path(os.path.realpath(os.path.expanduser(os.fspath(path))))
    allowed_resolved = [
        Path(os.path.realpath(os.path.expanduser(os.fspath(allowed_path))))
        for allowed_path in allowed
    ]
    if allowed_resolved and not any(
        resolved == allowed_path or allowed_path in resolved.parents
        for allowed_path in allowed_resolved
    ):
        return SourcePathTestResponse(
            path=raw_path,
            ok=False,
            exists=False,
            is_directory=False,
            readable=False,
            inside_allowed_roots=False,
            allowed_roots=allowed_roots,
            looks_like_host_path=looks_like_host_path or _looks_like_linux_host_path(raw_path),
            message="Root path is outside allowed source roots.",
            hint=hint,
        )

    # codeql[py/path-injection] resolved has passed configured allowed-root and realpath checks above.
    exists = resolved.exists()
    # codeql[py/path-injection] resolved has passed configured allowed-root and realpath checks above.
    is_directory = exists and resolved.is_dir()
    # codeql[py/path-injection] resolved has passed configured allowed-root and realpath checks above.
    readable = is_directory and os.access(resolved, os.R_OK | os.X_OK)

    if not exists:
        message = "Root path does not exist."
    elif not is_directory:
        message = "Root path is not a directory."
    elif not readable:
        message = "Path exists but OneSearch cannot read it. Check Docker volume permissions or PUID/PGID."
    else:
        message = "Path is ready to use."

    return SourcePathTestResponse(
        path=raw_path,
        ok=exists and is_directory and readable,
        exists=exists,
        is_directory=is_directory,
        readable=readable,
        inside_allowed_roots=True,
        allowed_roots=allowed_roots,
        looks_like_host_path=looks_like_host_path,
        message=message,
        hint=hint if not (exists and is_directory and readable) else None,
    )


def validate_root_path(root_path: Path | str) -> Path:
    """Validate that root_path exists, is a directory, and is within allowed paths."""
    raw_path = str(root_path).strip()
    if not raw_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Root path is required")

    root_path = Path(raw_path)
    allowed = _configured_allowed_paths()
    if allowed and not any(_is_within_path(root_path, allowed_path) for allowed_path in allowed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Root path is outside allowed directories",
        )

    resolved = Path(os.path.realpath(os.path.expanduser(os.fspath(root_path))))
    allowed_resolved = [
        Path(os.path.realpath(os.path.expanduser(os.fspath(allowed_path))))
        for allowed_path in allowed
    ]
    if allowed_resolved and not any(
        resolved == a or a in resolved.parents for a in allowed_resolved
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Root path is outside allowed directories",
        )

    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Root path does not exist"
        )
    if not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Root path is not a directory"
        )

    return resolved


def _remote_agent(db: Session, agent_id: str | None, *, online: bool = False) -> Agent:
    agent = db.get(Agent, agent_id) if agent_id else None
    if (
        agent is None
        or agent.approved_at is None
        or agent.token_hash is None
        or agent.status not in {"offline", "online"}
    ):
        raise HTTPException(status_code=409, detail="Agent is not available")
    if online and agent.status != "online":
        raise HTTPException(status_code=409, detail="agent_offline")
    return agent


def _canonical_remote_path(agent: Agent, root_path: str) -> str | None:
    if (
        not root_path
        or root_path != root_path.strip()
        or ".." in root_path.replace("\\", "/").split("/")
    ):
        return None
    windows = str(agent.platform).lower().startswith("win")
    path_class = PureWindowsPath if windows else PurePosixPath
    candidate = path_class(root_path)
    if windows:
        if not candidate.drive or "/" in root_path:
            return None
    elif not candidate.is_absolute() or "\\" in root_path:
        return None
    return str(candidate)


def _remote_path_authorized(agent: Agent, root_path: str) -> bool:
    canonical_root = _canonical_remote_path(agent, root_path)
    if canonical_root is None:
        return False
    windows = str(agent.platform).lower().startswith("win")
    path_class = PureWindowsPath if windows else PurePosixPath
    candidate = path_class(canonical_root)
    try:
        roots = json.loads(agent.allowed_roots)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(roots, list):
        return False
    for item in roots:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        try:
            parent = path_class(item["path"])
            if candidate == parent or parent in candidate.parents:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _require_remote_path_validation(
    db: Session, *, job_id: str | None, agent: Agent, root_path: str
) -> None:
    """Require recent durable evidence that this agent validated this exact root."""
    if not job_id:
        raise HTTPException(status_code=422, detail="Remote path validation is required")
    job = db.get(AgentJob, job_id)
    if job is None or job.kind != "browse" or job.reason != "validate":
        raise HTTPException(status_code=404, detail="Path validation not found")
    if job.agent_id != agent.id or job.status != "completed" or job.completed_at is None:
        raise HTTPException(status_code=409, detail="Remote path validation is not successful")
    completed_at = job.completed_at
    if completed_at.tzinfo is not None:
        completed_at = completed_at.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if completed_at < now - REMOTE_PATH_VALIDATION_MAX_AGE or completed_at > now:
        raise HTTPException(status_code=409, detail="Remote path validation has expired")
    try:
        payload = json.loads(job.payload)
    except (TypeError, json.JSONDecodeError):
        payload = None
    expected_path = _canonical_remote_path(agent, root_path)
    validated_path = (
        _canonical_remote_path(agent, payload.get("root_path"))
        if isinstance(payload, dict) and payload.get("operation") == "validate"
        and isinstance(payload.get("root_path"), str)
        else None
    )
    if expected_path is None or validated_path != expected_path:
        raise HTTPException(status_code=409, detail="Remote path validation does not match source path")


def _agent_allowed_root_paths(agent: Agent) -> list[str] | None:
    try:
        roots = json.loads(agent.allowed_roots)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(roots, list):
        return None
    paths: list[str] = []
    for root in roots:
        if not isinstance(root, dict) or not isinstance(root.get("path"), str):
            return None
        paths.append(root["path"])
    return paths


def _agent_allowed_root_ids(agent: Agent) -> set[str] | None:
    try:
        roots = json.loads(agent.allowed_roots)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(roots, list):
        return None
    ids = {item.get("root_id") for item in roots if isinstance(item, dict)}
    return ids if len(ids) == len(roots) and all(isinstance(root_id, str) for root_id in ids) else None


def _browse_payload(job: AgentJob) -> dict | None:
    try:
        payload = json.loads(job.payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or job.kind != "browse"
        or job.reason != "browse"
        or payload.get("operation") != "list"
        or not isinstance(payload.get("root_id"), str)
        or not isinstance(payload.get("path"), str)
    ):
        return None
    return payload


def _browse_response(job: AgentJob, payload: dict) -> SourceBrowseResponse:
    if job.status in {"pending", "claimed", "running", "cancelling"}:
        return SourceBrowseResponse.pending(
            job_id=job.id, status=job.status, root_id=payload["root_id"], path=payload["path"]
        )
    if job.status == "completed":
        try:
            checkpoint = json.loads(job.checkpoint)
            result = BrowseResult.model_validate(checkpoint["browse_result"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail="Browse result is unavailable") from None
        if result.root_id != payload["root_id"] or result.path != payload["path"]:
            raise HTTPException(status_code=409, detail="Browse result is unavailable")
        return SourceBrowseResponse.completed(job_id=job.id, result=result)
    if job.status in {"failed", "cancelled"}:
        return SourceBrowseResponse.pending(
            job_id=job.id, status=job.status, root_id=payload["root_id"], path=payload["path"]
        ).model_copy(update={"error": "Directory browse did not complete."})
    raise HTTPException(status_code=409, detail="Browse result is unavailable")


def _remote_path_result(
    job: AgentJob, agent: Agent | None, *, payload: object
) -> SourcePathTestResponse:
    root_path = payload.get("root_path") if isinstance(payload, dict) else None
    operation = payload.get("operation") if isinstance(payload, dict) else None
    allowed_roots = _agent_allowed_root_paths(agent) if agent is not None else None
    valid = (
        operation == "validate"
        and isinstance(root_path, str)
        and allowed_roots is not None
        and _remote_path_authorized(agent, root_path)
    )
    if not valid:
        return SourcePathTestResponse(
            path=root_path if isinstance(root_path, str) else "",
            ok=False,
            exists=False,
            is_directory=False,
            readable=False,
            inside_allowed_roots=False,
            allowed_roots=allowed_roots or [],
            message="Remote path validation result is unavailable.",
            job_id=job.id,
            status=job.status,
        )

    known_statuses = {
        "pending",
        "claimed",
        "running",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    }
    if job.status not in known_statuses:
        return SourcePathTestResponse(
            path=root_path,
            ok=False,
            exists=False,
            is_directory=False,
            readable=False,
            inside_allowed_roots=True,
            allowed_roots=allowed_roots,
            message="Remote path validation result is unavailable.",
            job_id=job.id,
            status=job.status,
        )

    completed = job.status == "completed"
    if completed:
        message = "Remote path is ready to use."
    elif job.status == "failed":
        message = "The agent could not validate this path."
    elif job.status == "cancelled":
        message = "Remote path validation was cancelled."
    else:
        message = "Remote path validation is still running."
    return SourcePathTestResponse(
        path=root_path,
        ok=completed,
        exists=completed,
        is_directory=completed,
        readable=completed,
        inside_allowed_roots=True,
        allowed_roots=allowed_roots,
        message=message,
        job_id=job.id,
        status=job.status,
    )


def _validate_source_location(
    db: Session,
    *,
    location_type: str,
    agent_id: str | None,
    processing_mode: str | None,
    root_path: str,
    allow_disabled_maintenance: bool = False,
) -> str:
    if location_type == "local":
        if agent_id is not None or processing_mode is not None:
            raise HTTPException(
                status_code=400, detail="Local sources cannot have an agent or processing mode"
            )
        return str(validate_root_path(root_path))
    if (
        not AppSettingsService(db).get_settings().remote_agents_enabled
        and not allow_disabled_maintenance
    ):
        raise HTTPException(status_code=409, detail="Remote agents are disabled")
    agent = _remote_agent(db, agent_id)
    if not _remote_path_authorized(agent, root_path):
        raise HTTPException(status_code=422, detail="Remote root path is not authorized")
    # Store the same canonical spelling used to bind validation evidence.
    canonical_path = _canonical_remote_path(agent, root_path)
    assert canonical_path is not None  # _remote_path_authorized checked it above.
    return canonical_path


def generate_source_id(name: str) -> str:
    """Generate a URL-safe source ID from name"""
    import re

    # Convert to lowercase, replace spaces with hyphens, remove non-alphanumeric
    source_id = name.lower().strip()
    source_id = re.sub(r"\s+", "-", source_id)
    source_id = re.sub(r"[^a-z0-9\-]", "", source_id)
    return source_id or "source"


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    List all configured sources

    Returns list of sources with configuration details
    """
    stmt = select(Source).order_by(Source.created_at.desc())
    sources = db.execute(stmt).scalars().all()
    default = AppSettingsService(db).get_settings().default_scan_schedule
    default_schedule = default.model_dump() if default else None
    return [
        SourceResponse.from_orm_model(
            s,
            effective_schedule=ScheduleConfig(
                **resolve_effective_schedule(s, db, default_schedule)
            ),
        )
        for s in sources
    ]


@router.post("/test-path", response_model=SourcePathTestResponse)
async def test_source_path(
    request_data: SourcePathTestRequest,
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency declaration
    current_user: User = Depends(get_current_user),
):
    """Test a source path before saving it."""
    if request_data.location_type == "local":
        return build_source_path_test_response(request_data.root_path)
    if not AppSettingsService(db).get_settings().remote_agents_enabled:
        raise HTTPException(status_code=409, detail="Remote agents are disabled")
    agent = _remote_agent(db, request_data.agent_id, online=True)
    if not _remote_path_authorized(agent, request_data.root_path):
        raise HTTPException(status_code=422, detail="Remote root path is not authorized")
    job = AgentJobService(db).enqueue_browse(agent.id, request_data.root_path)
    db.commit()
    return SourcePathTestResponse(
        path=request_data.root_path,
        ok=False,
        exists=False,
        is_directory=False,
        readable=False,
        inside_allowed_roots=True,
        allowed_roots=[],
        message="Remote path validation is queued.",
        job_id=job.id,
        status=job.status,
    )


@router.get("/test-path/{job_id}", response_model=SourcePathTestResponse)
async def get_source_path_test(
    job_id: str,
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency declaration
    current_user: User = Depends(get_current_user),  # noqa: B008
):
    """Return the sanitized result of a queued remote path validation."""
    job = db.get(AgentJob, job_id)
    if job is None or job.kind != "browse" or job.reason != "validate":
        raise HTTPException(status_code=404, detail="Path validation not found")
    try:
        payload: object = json.loads(job.payload)
    except (TypeError, json.JSONDecodeError):
        payload = None
    return _remote_path_result(job, db.get(Agent, job.agent_id), payload=payload)


@router.post("/browse", response_model=SourceBrowseResponse)
async def browse_source_directory(
    request_data: SourceBrowseRequest,
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency declaration
    current_user: User = Depends(get_current_user),  # noqa: B008
):
    """Queue a bounded directory-only browse; this never creates a source."""
    if not AppSettingsService(db).get_settings().remote_agents_enabled:
        raise HTTPException(status_code=409, detail="Remote agents are disabled")
    agent = _remote_agent(db, request_data.agent_id, online=True)
    root_ids = _agent_allowed_root_ids(agent)
    if root_ids is None or request_data.root_id not in root_ids:
        raise HTTPException(status_code=422, detail="Remote root is not authorized")
    try:
        # Reuse the wire contract's canonical-relative validation before persistence.
        path = BrowseResult(
            root_id=request_data.root_id, path=request_data.path, entries=[], truncated=False
        ).path
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Browse path is invalid") from error
    job = AgentJobService(db).enqueue_browse_list(agent.id, request_data.root_id, path)
    db.commit()
    return SourceBrowseResponse.pending(
        job_id=job.id, status=job.status, root_id=request_data.root_id, path=path
    )


@router.get("/browse/{job_id}", response_model=SourceBrowseResponse)
async def get_source_directory_browse(
    job_id: str,
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency declaration
    current_user: User = Depends(get_current_user),  # noqa: B008
):
    job = db.get(AgentJob, job_id)
    payload = _browse_payload(job) if job is not None else None
    if payload is None:
        raise HTTPException(status_code=404, detail="Browse job not found")
    return _browse_response(job, payload)


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    Get a specific source by ID

    Args:
        source_id: Source identifier

    Returns:
        Source configuration details

    Raises:
        404: Source not found
    """
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{source_id}' not found"
        )
    effective_schedule = resolve_effective_schedule(source, db)
    return SourceResponse.from_orm_model(
        source, effective_schedule=ScheduleConfig(**effective_schedule)
    )


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    request: Request,
    source_data: SourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new search source

    Args:
        source_data: Source configuration including name, path, patterns

    Returns:
        Created source with generated ID

    Raises:
        400: Invalid configuration or duplicate ID
    """
    # Generate ID if not provided
    source_id = source_data.id or generate_source_id(source_data.name)

    # Check if ID already exists
    existing = db.get(Source, source_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source with ID '{source_id}' already exists",
        )

    root_path = _validate_source_location(
        db,
        location_type=source_data.location_type,
        agent_id=source_data.agent_id,
        processing_mode=source_data.processing_mode,
        root_path=source_data.root_path,
    )
    if source_data.location_type == "agent":
        _require_remote_path_validation(
            db,
            job_id=source_data.path_validation_job_id,
            agent=_remote_agent(db, source_data.agent_id),
            root_path=root_path,
        )

    # Validate schedule if provided and not following the global default
    if not source_data.use_default_schedule:
        if source_data.schedule_type == "interval":
            if not validate_interval(source_data.interval_value, source_data.interval_unit):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid interval: {source_data.interval_value} {source_data.interval_unit}",
                )
        elif source_data.scan_schedule and not validate_schedule(source_data.scan_schedule):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scan schedule: {source_data.scan_schedule}",
            )

    # Serialize patterns to JSON
    include_patterns = (
        json.dumps(source_data.include_patterns) if source_data.include_patterns else None
    )
    exclude_patterns = (
        json.dumps(source_data.exclude_patterns) if source_data.exclude_patterns else None
    )

    # Create source
    source = Source(
        id=source_id,
        name=source_data.name,
        root_path=str(root_path),
        location_type=source_data.location_type,
        agent_id=source_data.agent_id,
        processing_mode=source_data.processing_mode,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        scan_schedule=source_data.scan_schedule or None,
        schedule_type=source_data.schedule_type,
        interval_value=source_data.interval_value,
        interval_unit=source_data.interval_unit,
        use_default_schedule=source_data.use_default_schedule,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    # Compute next_scan_at from the resolved effective schedule (own schedule or
    # the global default) so it's correct even without a live scheduler attached.
    effective_schedule = resolve_effective_schedule(source, db)
    source.next_scan_at = calculate_next_run_time_for_schedule(**effective_schedule)
    db.commit()

    logger.info(f"Created source: {source_id} at {source.root_path}")

    # Register schedule with the scheduler (keeps APScheduler in sync)
    if hasattr(request.app.state, "scheduler"):
        request.app.state.scheduler.update_source_schedule(source_id)
        db.refresh(source)

    effective_schedule = resolve_effective_schedule(source, db)
    return SourceResponse.from_orm_model(
        source, effective_schedule=ScheduleConfig(**effective_schedule)
    )


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    request: Request,
    source_id: str,
    source_data: SourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update an existing source configuration

    Args:
        source_id: Source identifier
        source_data: Updated source configuration

    Returns:
        Updated source details

    Raises:
        404: Source not found
        400: Invalid configuration
    """
    # Get existing source
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{source_id}' not found"
        )

    # Validate the prospective combined binding before mutating the persistent object.
    prospective = {
        "location_type": source.location_type,
        "agent_id": source.agent_id,
        "processing_mode": source.processing_mode,
        "root_path": source.root_path,
    }
    for field in prospective:
        if field in source_data.model_fields_set:
            prospective[field] = getattr(source_data, field)

    # The form submits the current binding with ordinary edits. Treat a spelling
    # which canonicalizes to the stored remote path as maintenance, too.
    existing_agent = db.get(Agent, source.agent_id) if source.location_type == "agent" else None
    stored_canonical_path = (
        _canonical_remote_path(existing_agent, source.root_path)
        if existing_agent is not None
        else None
    )
    candidate_path = (
        _canonical_remote_path(existing_agent, prospective["root_path"])
        if source.location_type == "agent"
        and prospective["location_type"] == "agent"
        and source.agent_id == prospective["agent_id"]
        and existing_agent is not None
        else None
    )
    unchanged_remote_binding = (
        candidate_path is not None and candidate_path == stored_canonical_path
    )
    root_path = _validate_source_location(
        db,
        **prospective,
        allow_disabled_maintenance=unchanged_remote_binding,
    )
    remote_binding_changed = prospective["location_type"] == "agent" and (
        source.location_type != "agent"
        or source.agent_id != prospective["agent_id"]
        or stored_canonical_path != root_path
    )
    if remote_binding_changed:
        _require_remote_path_validation(
            db,
            job_id=source_data.path_validation_job_id,
            agent=_remote_agent(db, prospective["agent_id"]),
            root_path=root_path,
        )
    source.location_type, source.agent_id, source.processing_mode, source.root_path = (
        prospective["location_type"],
        prospective["agent_id"],
        prospective["processing_mode"],
        str(root_path),
    )

    # Update fields if provided
    if source_data.name is not None:
        source.name = source_data.name

    if source_data.include_patterns is not None:
        source.include_patterns = json.dumps(source_data.include_patterns)

    if source_data.exclude_patterns is not None:
        source.exclude_patterns = json.dumps(source_data.exclude_patterns)

    # Handle schedule updates
    schedule_fields_changed = bool(
        {
            "scan_schedule",
            "schedule_type",
            "interval_value",
            "interval_unit",
            "use_default_schedule",
        }
        & source_data.model_fields_set
    )

    if "scan_schedule" in source_data.model_fields_set:
        source.scan_schedule = source_data.scan_schedule or None
    if "schedule_type" in source_data.model_fields_set:
        source.schedule_type = source_data.schedule_type
    if "interval_value" in source_data.model_fields_set:
        source.interval_value = source_data.interval_value
    if "interval_unit" in source_data.model_fields_set:
        source.interval_unit = source_data.interval_unit
    if "use_default_schedule" in source_data.model_fields_set:
        source.use_default_schedule = source_data.use_default_schedule

    if schedule_fields_changed and not source.use_default_schedule:
        if source.schedule_type == "interval":
            if not validate_interval(source.interval_value, source.interval_unit):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid interval: {source.interval_value} {source.interval_unit}",
                )
        elif source.scan_schedule and not validate_schedule(source.scan_schedule):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scan schedule: {source.scan_schedule}",
            )

    if schedule_fields_changed:
        effective_schedule = resolve_effective_schedule(source, db)
        source.next_scan_at = calculate_next_run_time_for_schedule(**effective_schedule)

    # Update timestamp
    source.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.commit()
    db.refresh(source)

    # Sync schedule with scheduler (keeps APScheduler in sync)
    if schedule_fields_changed and hasattr(request.app.state, "scheduler"):
        request.app.state.scheduler.update_source_schedule(source_id)
        db.refresh(source)

    logger.info(f"Updated source: {source_id}")

    effective_schedule = resolve_effective_schedule(source, db)
    return SourceResponse.from_orm_model(
        source, effective_schedule=ScheduleConfig(**effective_schedule)
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    request: Request,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a source and all its indexed files

    Removes:
    - Source configuration from database
    - All indexed_files records for this source (cascade)
    - All documents from Meilisearch index

    Args:
        source_id: Source identifier

    Raises:
        404: Source not found
    """
    # Get source
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{source_id}' not found"
        )

    # Count indexed files for logging
    stmt = select(func.count()).where(IndexedFile.source_id == source_id)
    indexed_files_count = db.execute(stmt).scalar() or 0

    # Delete all documents for this source from Meilisearch using filter
    # This handles any document ID format (old or new) for seamless migration
    # Use json.dumps to escape source_id and prevent filter injection
    try:
        escaped_id = json.dumps(source_id)
        await meili_service.delete_documents_by_filter(f"source_id = {escaped_id}")
    except Exception as e:
        logger.warning(f"Failed to delete documents from Meilisearch for source {source_id}: {e}")

    # Remove scheduled job if any
    if hasattr(request.app.state, "scheduler"):
        request.app.state.scheduler.remove_source(source_id)

    # Clean up stored previews for this source
    try:
        from app.config import settings as runtime_settings
        from app.services.preview_assets import app_data_preview_directory, delete_source_previews
        preview_base = app_data_preview_directory(runtime_settings.database_url)
        delete_source_previews(source_id, preview_base)
    except Exception as e:
        logger.warning(f"Failed to clean up previews for source {source_id}: {e}")

    # Delete source (cascade will delete indexed_files)
    db.delete(source)
    db.commit()

    logger.info(f"Deleted source: {source_id} ({indexed_files_count} indexed files removed)")

    return None


@router.post("/{source_id}/reindex")
async def reindex_source(
    source_id: str,
    full: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger reindexing for a source

    By default performs incremental indexing:
    - Only reindexes changed files (based on mtime/size)
    - Adds new files
    - Removes deleted files

    With full=true, performs complete rebuild:
    - Clears all existing documents from search index
    - Clears indexed file records from database
    - Re-indexes all files from scratch
    - Use for migration or to fix index corruption
    """
    # Get source
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{source_id}' not found"
        )

    if source.location_type == "agent":
        try:
            existing = db.scalar(select(AgentJob).where(AgentJob.active_key == source_id))
            job = await ScanDispatcher(db, meili_service).dispatch(source_id, "manual", full=full)
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RemoteAgentsDisabledError as exc:
            raise HTTPException(status_code=409, detail="remote_agents_disabled") from exc
        except AgentUnavailableError as exc:
            raise HTTPException(status_code=409, detail="agent_unavailable") from exc
        db.commit()
        return JSONResponse(
            status_code=202,
            content={
                "message": f"Remote reindex queued for source '{source_id}'",
                "job_id": job.id,
                "status": job.status,
                "coalesced": existing is not None,
            },
        )

    # Acquire lock (non-blocking) to prevent concurrent indexing
    lock = get_source_lock(source_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Indexing already in progress for source '{source_id}'",
        )

    logger.info(f"Starting reindex for source: {source_id}")

    try:
        from sqlalchemy.orm import sessionmaker
        from starlette.concurrency import run_in_threadpool

        db_bind = db.get_bind()

        def sync_index_wrapper():
            import asyncio

            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_bind)
            thread_db = SessionLocal()

            try:
                loop = asyncio.new_event_loop()
                try:
                    stats = loop.run_until_complete(
                        ScanDispatcher(thread_db, meili_service).dispatch(
                            source_id, "manual", full=full
                        )
                    )

                    # Update last_scan_at
                    source_record = thread_db.get(Source, source_id)
                    if source_record:
                        source_record.last_scan_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        thread_db.commit()

                    return stats
                finally:
                    loop.close()
            finally:
                thread_db.close()

        stats = await run_in_threadpool(sync_index_wrapper)

        logger.info(
            f"Reindex complete for '{source_id}': "
            f"{stats.successful} successful, {stats.failed} failed, {stats.skipped} skipped"
        )

        return {
            "message": f"Reindexing completed for source '{source_id}'",
            "stats": stats.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reindexing failed for source '{source_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reindexing failed due to an internal error",
        )
    finally:
        lock.release()


@router.post("/{source_id}/clear-stale")
async def clear_stale_failed_files(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clean failed file entries for a source.

    Missing files are removed. Existing failed files are retried through the normal
    indexing path. Files that still fail remain visible with a fresh error.
    """
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{source_id}' not found"
        )

    lock = get_source_lock(source_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Indexing already in progress for source '{source_id}'",
        )

    try:
        failed_files = (
            db.execute(
                select(IndexedFile).where(
                    IndexedFile.source_id == source_id, IndexedFile.status == "failed"
                )
            )
            .scalars()
            .all()
        )

        include_patterns = json.loads(source.include_patterns) if source.include_patterns else None
        exclude_patterns = json.loads(source.exclude_patterns) if source.exclude_patterns else None
        current_files = set(
            FileScanner(
                root_path=source.root_path,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            ).scan()
        )

        indexing_service = IndexingService(db, meili_service)
        cleared = 0
        reindexed = 0
        still_failed = 0
        skipped = 0

        for indexed_file in failed_files:
            if not Path(indexed_file.path).exists() or indexed_file.path not in current_files:
                path_hash = hashlib.sha256(indexed_file.path.encode()).hexdigest()[:12]
                doc_id = f"{source_id}--{path_hash}"
                try:
                    await meili_service.delete_document(doc_id)
                except Exception as e:
                    logger.warning(
                        f"Meilisearch delete failed for stale failed file {indexed_file.path}: {e}"
                    )
                db.delete(indexed_file)
                cleared += 1
                continue

            result = await indexing_service.retry_failed_file(source, indexed_file.path)
            if result == "success":
                reindexed += 1
            elif result == "skipped":
                skipped += 1
            else:
                still_failed += 1

        db.commit()
        logger.info(
            f"Cleaned failed files for source '{source_id}': "
            f"{cleared} cleared, {reindexed} reindexed, {still_failed} still failed, {skipped} skipped"
        )
        return {
            "cleared": cleared,
            "reindexed": reindexed,
            "still_failed": still_failed,
            "skipped": skipped,
        }
    finally:
        lock.release()
