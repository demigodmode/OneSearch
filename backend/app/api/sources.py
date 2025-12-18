# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Source management API endpoints
Provides CRUD operations for search sources
"""
import json
import logging
from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db.database import get_db
from ..models import Source, IndexedFile
from ..schemas import SourceCreate, SourceUpdate, SourceResponse
from ..services.search import SearchService, meili_service
from ..services.indexer import IndexingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])


def generate_source_id(name: str) -> str:
    """Generate a URL-safe source ID from name"""
    import re
    # Convert to lowercase, replace spaces with hyphens, remove non-alphanumeric
    source_id = name.lower().strip()
    source_id = re.sub(r'\s+', '-', source_id)
    source_id = re.sub(r'[^a-z0-9\-]', '', source_id)
    return source_id or "source"


@router.get("", response_model=List[SourceResponse])
async def list_sources(db: Session = Depends(get_db)):
    """
    List all configured sources

    Returns list of sources with configuration details
    """
    stmt = select(Source).order_by(Source.created_at.desc())
    sources = db.execute(stmt).scalars().all()
    return [SourceResponse.from_orm_model(s) for s in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: Session = Depends(get_db)):
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
async def create_source(source_data: SourceCreate, db: Session = Depends(get_db)):
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

    # Validate root_path exists
    from pathlib import Path
    root_path = Path(source_data.root_path)
    if not root_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Root path does not exist: {source_data.root_path}"
        )
    if not root_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Root path is not a directory: {source_data.root_path}"
        )

    # Serialize patterns to JSON
    include_patterns = json.dumps(source_data.include_patterns) if source_data.include_patterns else None
    exclude_patterns = json.dumps(source_data.exclude_patterns) if source_data.exclude_patterns else None

    # Create source
    source = Source(
        id=source_id,
        name=source_data.name,
        root_path=str(root_path.resolve()),  # Store absolute path
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    logger.info(f"Created source: {source_id} at {source.root_path}")

    return SourceResponse.from_orm_model(source)


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    source_data: SourceUpdate,
    db: Session = Depends(get_db)
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
        from pathlib import Path
        root_path = Path(source_data.root_path)
        if not root_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Root path does not exist: {source_data.root_path}"
            )
        if not root_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Root path is not a directory: {source_data.root_path}"
            )
        source.root_path = str(root_path.resolve())

    if source_data.include_patterns is not None:
        source.include_patterns = json.dumps(source_data.include_patterns)

    if source_data.exclude_patterns is not None:
        source.exclude_patterns = json.dumps(source_data.exclude_patterns)

    # Update timestamp
    source.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(source)

    logger.info(f"Updated source: {source_id}")

    return SourceResponse.from_orm_model(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str, db: Session = Depends(get_db)):
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

    # Get all indexed files for cleanup
    stmt = select(IndexedFile).where(IndexedFile.source_id == source_id)
    indexed_files = db.execute(stmt).scalars().all()

    # Delete documents from Meilisearch
    for indexed_file in indexed_files:
        doc_id = f"{source_id}:{indexed_file.path}"
        try:
            await meili_service.delete_document(doc_id)
        except Exception as e:
            logger.warning(f"Failed to delete document from Meilisearch: {doc_id}: {e}")

    # Delete source (cascade will delete indexed_files)
    db.delete(source)
    db.commit()

    logger.info(f"Deleted source: {source_id} ({len(indexed_files)} indexed files removed)")

    return None


@router.post("/{source_id}/reindex")
async def reindex_source(source_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger reindexing for a source

    Performs incremental indexing:
    - Only reindexes changed files (based on mtime/size)
    - Adds new files
    - Removes deleted files
    - Updates Meilisearch index

    Args:
        source_id: Source identifier

    Returns:
        Indexing statistics including:
        - total_scanned: Total files scanned
        - new_files: Newly indexed files
        - modified_files: Re-indexed modified files
        - unchanged_files: Skipped unchanged files
        - deleted_files: Removed deleted files
        - successful: Successfully indexed count
        - failed: Failed indexing count
        - skipped: Unsupported file types

    Raises:
        404: Source not found
        500: Indexing failed
    """
    # Get source
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found"
        )

    logger.info(f"Starting reindex for source: {source_id}")

    try:
        # Run indexing in thread pool to prevent blocking the event loop
        # index_source performs blocking file I/O and synchronous DB operations
        from starlette.concurrency import run_in_threadpool
        from sqlalchemy.orm import sessionmaker
        from ..db.database import engine

        # Create a thread-safe wrapper that creates its own DB session
        def sync_index_wrapper():
            import asyncio

            # Create a new DB session for this thread (thread-safe)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            thread_db = SessionLocal()

            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                try:
                    # Create indexing service with thread-local session
                    indexing_service = IndexingService(thread_db, meili_service)
                    return loop.run_until_complete(indexing_service.index_source(source_id))
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

    except Exception as e:
        logger.error(f"Reindexing failed for source '{source_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reindexing failed: {str(e)}"
        )
