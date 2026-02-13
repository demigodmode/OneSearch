# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Source management API endpoints
Provides CRUD operations for search sources
"""
import json
import logging
from typing import List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from pathlib import Path

from ..config import settings
from ..db.database import get_db
from ..models import Source, IndexedFile, User
from ..schemas import SourceCreate, SourceUpdate, SourceResponse
from ..services.search import SearchService, meili_service
from ..services.indexer import IndexingService
from ..services.scheduler import validate_schedule, get_source_lock, calculate_next_run_time
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])


def validate_root_path(root_path: Path) -> Path:
    """Validate that root_path exists, is a directory, and is within allowed paths."""
    if not root_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Root path does not exist: {root_path}"
        )
    if not root_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Root path is not a directory: {root_path}"
        )

    resolved = root_path.resolve()
    allowed = [Path(p.strip()).resolve() for p in settings.allowed_source_paths.split(",") if p.strip()]
    if allowed and not any(resolved == a or a in resolved.parents for a in allowed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Root path is outside allowed directories ({settings.allowed_source_paths})"
        )
    return resolved


def generate_source_id(name: str) -> str:
    """Generate a URL-safe source ID from name"""
    import re
    # Convert to lowercase, replace spaces with hyphens, remove non-alphanumeric
    source_id = name.lower().strip()
    source_id = re.sub(r'\s+', '-', source_id)
    source_id = re.sub(r'[^a-z0-9\-]', '', source_id)
    return source_id or "source"


@router.get("", response_model=List[SourceResponse])
async def list_sources(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    List all configured sources

    Returns list of sources with configuration details
    """
    stmt = select(Source).order_by(Source.created_at.desc())
    sources = db.execute(stmt).scalars().all()
    return [SourceResponse.from_orm_model(s) for s in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found"
        )
    return SourceResponse.from_orm_model(source)


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(request: Request, source_data: SourceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
            detail=f"Source with ID '{source_id}' already exists"
        )

    # Validate root_path exists and is within allowed directories
    root_path = validate_root_path(Path(source_data.root_path))

    # Validate schedule if provided
    if source_data.scan_schedule and not validate_schedule(source_data.scan_schedule):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scan schedule: {source_data.scan_schedule}"
        )

    # Serialize patterns to JSON
    include_patterns = json.dumps(source_data.include_patterns) if source_data.include_patterns else None
    exclude_patterns = json.dumps(source_data.exclude_patterns) if source_data.exclude_patterns else None

    # Calculate next_scan_at if schedule provided
    next_scan_at = None
    if source_data.scan_schedule:
        next_scan_at = calculate_next_run_time(source_data.scan_schedule)

    # Create source
    source = Source(
        id=source_id,
        name=source_data.name,
        root_path=str(root_path),  # Already resolved by validate_root_path
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        scan_schedule=source_data.scan_schedule or None,
        next_scan_at=next_scan_at,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    logger.info(f"Created source: {source_id} at {source.root_path}")

    # Register schedule with the scheduler (keeps APScheduler in sync)
    if source.scan_schedule and hasattr(request.app.state, "scheduler"):
        request.app.state.scheduler.update_source_schedule(source_id, source.scan_schedule)

    return SourceResponse.from_orm_model(source)


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
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found"
        )

    # Update fields if provided
    if source_data.name is not None:
        source.name = source_data.name

    if source_data.root_path is not None:
        resolved = validate_root_path(Path(source_data.root_path))
        source.root_path = str(resolved)

    if source_data.include_patterns is not None:
        source.include_patterns = json.dumps(source_data.include_patterns)

    if source_data.exclude_patterns is not None:
        source.exclude_patterns = json.dumps(source_data.exclude_patterns)

    # Handle schedule updates
    if "scan_schedule" in source_data.model_fields_set:
        new_schedule = source_data.scan_schedule or None
        if new_schedule and not validate_schedule(new_schedule):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scan schedule: {new_schedule}"
            )
        source.scan_schedule = new_schedule
        # Calculate next_scan_at directly so response is always accurate
        source.next_scan_at = calculate_next_run_time(new_schedule) if new_schedule else None

    # Update timestamp
    source.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.commit()
    db.refresh(source)

    # Sync schedule with scheduler (keeps APScheduler in sync)
    if "scan_schedule" in source_data.model_fields_set and hasattr(request.app.state, "scheduler"):
        request.app.state.scheduler.update_source_schedule(source_id, source.scan_schedule)

    logger.info(f"Updated source: {source_id}")

    return SourceResponse.from_orm_model(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(request: Request, source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found"
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found"
        )

    # Acquire lock (non-blocking) to prevent concurrent indexing
    lock = get_source_lock(source_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Indexing already in progress for source '{source_id}'"
        )

    logger.info(f"Starting reindex for source: {source_id}")

    try:
        from starlette.concurrency import run_in_threadpool
        from sqlalchemy.orm import sessionmaker
        from ..db.database import engine

        def sync_index_wrapper():
            import asyncio

            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            thread_db = SessionLocal()

            try:
                loop = asyncio.new_event_loop()
                try:
                    indexing_service = IndexingService(thread_db, meili_service)
                    stats = loop.run_until_complete(indexing_service.index_source(source_id, full=full))

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
            "stats": stats.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reindexing failed for source '{source_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reindexing failed due to an internal error"
        )
    finally:
        lock.release()
