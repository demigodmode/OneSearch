# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Search API endpoint
Provides full-text search across indexed documents
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Agent, Source, User
from ..schemas import Document, SearchQuery, SearchResponse, SearchResult
from ..services.agent_auth import effective_agent_status
from ..services.app_settings import AppSettingsService
from ..services.search import meili_service
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])

# Rounding precision (decimal places) applied to the Meili _rankingScore when
# grouping hits into a "near-equal relevance" band for the availability tie-breaker.
_TIE_BREAK_PRECISION = 3


def _apply_relevance_tiebreak(results: list[SearchResult]) -> None:
    """In-place stable re-sort: relevance band is primary, availability (online/local) breaks near-equal ties."""
    results.sort(
        key=lambda r: (
            -round(r.score, _TIE_BREAK_PRECISION),
            0 if (r.agent_status is None or r.agent_status == "online") else 1,
        )
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    query: SearchQuery,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Search indexed documents with filters

    Performs full-text search across all indexed documents with:
    - Typo tolerance
    - Relevance ranking
    - Content snippet highlighting
    - Filtering by source and file type

    Args:
        query: Search parameters including:
            - q: Query string (required)
            - source_id: Filter by specific source (optional)
            - type: Filter by file type (text, markdown, pdf) (optional)
            - limit: Max results to return (1-100, default 20)
            - offset: Pagination offset (default 0)

    Returns:
        Search results with:
        - results: List of matching documents
        - total: Total matching documents
        - limit: Results limit used
        - offset: Offset used
        - processing_time_ms: Search processing time

    Raises:
        400: Invalid query parameters
        500: Search engine error
    """
    # Validate query
    if not query.q or not query.q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string cannot be empty"
        )

    try:
        # Build filter conditions using array-based filters with proper escaping
        # Meilisearch automatically ANDs array elements
        # Use json.dumps() to safely escape string values and prevent filter injection
        filters_list = []
        if query.source_id:
            # json.dumps ensures proper escaping of quotes and special characters
            escaped_source_id = json.dumps(query.source_id)
            filters_list.append(f'source_id = {escaped_source_id}')
        if query.type:
            escaped_type = json.dumps(query.type)
            filters_list.append(f'type = {escaped_type}')

        # Pass as array or None (Meilisearch accepts both string and array)
        filters = filters_list if filters_list else None

        # Execute search
        logger.debug(
            f"Executing search: q='{query.q}', filters={filters}, "
            f"limit={query.limit}, offset={query.offset}"
        )

        results = await meili_service.search(
            query=query.q,
            filters=filters,
            limit=query.limit,
            offset=query.offset,
            sort=query.sort if query.sort and query.sort != 'relevance' else None,
            crop_length=query.snippet_length,
        )

        # Batch-load agent liveness for every source referenced by a hit, so we can
        # attach a live agent_status per result without doing an N+1 query per hit.
        hits = results.get("hits", [])
        source_ids = {hit["source_id"] for hit in hits if hit.get("source_id")}
        status_by_source: dict[str, str | None] = {}
        if source_ids:
            app_settings = AppSettingsService(db).get_settings()
            rows = (
                db.query(Source.id, Source.location_type, Agent)
                .outerjoin(Agent, Source.agent_id == Agent.id)
                .filter(Source.id.in_(source_ids))
                .all()
            )
            for source_id, location_type, agent in rows:
                if location_type != "agent":
                    status_by_source[source_id] = None
                else:
                    status_by_source[source_id] = effective_agent_status(
                        agent, remote_agents_enabled=app_settings.remote_agents_enabled
                    )

        # Transform results to response format
        search_results = []
        for hit in hits:
            # Extract content snippet with highlighting
            # Meilisearch provides _formatted field with <em> tags for matches
            formatted = hit.get("_formatted", hit)
            snippet = formatted.get("content", "")[:query.snippet_length]
            if len(hit.get("content", "")) > query.snippet_length:
                snippet += "..."

            search_results.append(SearchResult(
                id=hit["id"],
                path=hit["path"],
                basename=hit["basename"],
                source_name=hit["source_name"],
                type=hit["type"],
                size_bytes=hit["size_bytes"],
                modified_at=hit["modified_at"],
                snippet=snippet,
                # 0.0 fallback is only safe because the service layer passes
                # showRankingScore=True to Meili, so _rankingScore is always present.
                score=hit.get("_rankingScore", 0.0),
                source_id=hit.get("source_id", ""),
                # Absent key (source row gone -> stale/orphaned index entry) reads as
                # "offline"; local sources are stored as an explicit None (available).
                agent_status=status_by_source.get(hit.get("source_id"), "offline"),
            ))

        # Availability is a relevance tie-breaker only: only reorder when no explicit
        # sort was requested. An online/local source wins over an offline one at equal
        # relevance; explicit sorts (e.g. modified_at) are never touched.
        if not query.sort or query.sort == "relevance":
            _apply_relevance_tiebreak(search_results)

        response = SearchResponse(
            results=search_results,
            total=results.get("estimatedTotalHits", 0),
            limit=query.limit,
            offset=query.offset,
            processing_time_ms=results.get("processingTimeMs", 0)
        )

        logger.info(
            f"Search complete: '{query.q}' returned {len(search_results)}/{response.total} results "
            f"in {response.processing_time_ms}ms"
        )

        return response

    except Exception as e:
        logger.error(f"Search failed for query '{query.q}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your search"
        )


@router.get("/documents/{document_id}", response_model=Document)
async def get_document(document_id: str, current_user: User = Depends(get_current_user)):
    """
    Get a single document by ID

    Retrieves the full document content and metadata from the search index.
    Document IDs have the format: {source_id}--{path_hash}

    Args:
        document_id: Unique document identifier

    Returns:
        Full document with content and metadata

    Raises:
        404: Document not found
        500: Failed to retrieve document
    """
    try:
        document = await meili_service.get_document(document_id)

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document not found: {document_id}"
            )

        logger.info(f"Retrieved document: {document_id}")
        return document

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document {document_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving the document"
        )
