"""
Search API endpoint
Provides full-text search across indexed documents
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from ..schemas import SearchQuery, SearchResponse, SearchResult
from ..services.search import SearchService, meili_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(query: SearchQuery):
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
        # Build filter conditions using array-based filters (safer than string concatenation)
        # Meilisearch automatically ANDs array elements
        filters_list = []
        if query.source_id:
            # Use array-based filters with proper quoting - Meilisearch handles escaping
            filters_list.append(f'source_id = "{query.source_id}"')
        if query.type:
            filters_list.append(f'type = "{query.type}"')

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
            offset=query.offset
        )

        # Transform results to response format
        search_results = []
        for hit in results.get("hits", []):
            # Extract content snippet with highlighting
            # Meilisearch provides _formatted field with <em> tags for matches
            formatted = hit.get("_formatted", hit)
            snippet = formatted.get("content", "")[:300]  # First 300 chars
            if len(hit.get("content", "")) > 300:
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
                score=hit.get("_rankingScore", 0.0)
            ))

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
        logger.error(f"Search failed for query '{query.q}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
