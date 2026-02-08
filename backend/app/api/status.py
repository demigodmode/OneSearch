# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Status and health API endpoints
Provides system health checks and per-source indexing status
"""
import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import User
from ..services.indexer import IndexingService
from ..services.search import SearchService, meili_service
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
async def get_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Get indexing status for all sources

    Returns comprehensive status for each configured source including:
    - Total files indexed
    - Successful/failed/skipped counts
    - Last indexed timestamp
    - Failed files with error messages

    Returns:
        List of per-source status objects
    """
    # Initialize indexing service
    indexing_service = IndexingService(db, meili_service)

    # Get all sources
    from sqlalchemy import select
    from ..models import Source

    stmt = select(Source).order_by(Source.created_at.desc())
    sources = db.execute(stmt).scalars().all()

    # Get status for each source
    status_list = []
    for source in sources:
        try:
            source_status = indexing_service.get_source_status(source.id)
            status_list.append(source_status)
        except Exception as e:
            logger.error(f"Failed to get status for source {source.id}: {e}")
            # Return partial status even if one fails
            status_list.append({
                "source_id": source.id,
                "source_name": source.name,
                "error": str(e),
            })

    return {"sources": status_list}


@router.get("/status/{source_id}")
async def get_source_status(source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Get detailed indexing status for a specific source

    Args:
        source_id: Source identifier

    Returns:
        Detailed status including:
        - source_id: Source identifier
        - source_name: Source name
        - total_files: Total number of indexed files
        - successful: Successfully indexed files
        - failed: Failed files count
        - skipped: Skipped files count
        - last_indexed_at: Last indexing timestamp
        - failed_files: List of failed files with error messages (up to 50)

    Raises:
        404: Source not found
    """
    from fastapi import HTTPException, status

    # Initialize indexing service
    indexing_service = IndexingService(db, meili_service)

    try:
        source_status = indexing_service.get_source_status(source_id)
        return source_status
    except ValueError as e:
        # Source not found
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to get status for source {source_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving source status"
        )
