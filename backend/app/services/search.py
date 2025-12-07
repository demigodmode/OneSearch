"""
Meilisearch client wrapper and document indexing
"""
import logging
from typing import List, Dict, Any, Optional

import meilisearch
from meilisearch.client import Client
from meilisearch.index import Index

from ..config import settings

logger = logging.getLogger(__name__)

# Document schema constants
INDEX_NAME = "documents"
SEARCHABLE_FIELDS = ["content", "basename", "path", "title"]
FILTERABLE_FIELDS = ["source_id", "type", "extension", "modified_at"]
SORTABLE_FIELDS = ["modified_at", "size_bytes", "basename"]


class MeilisearchService:
    """
    Meilisearch client wrapper for OneSearch

    Handles connection, index management, and search operations
    """

    def __init__(self):
        """Initialize Meilisearch client"""
        self.client: Optional[Client] = None
        self.index: Optional[Index] = None

    def connect(self) -> bool:
        """
        Connect to Meilisearch and initialize index

        Returns:
            bool: True if connection successful
        """
        try:
            self.client = Client(settings.meili_url, settings.meili_master_key)

            # Test connection
            self.client.health()

            # Get or create index with primary key
            # This ensures the index exists before we try to configure it
            self.index = self.client.get_or_create_index(
                INDEX_NAME,
                {"primaryKey": "id"}
            )

            # Configure index settings
            self._configure_index()

            logger.info(f"Connected to Meilisearch at {settings.meili_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Meilisearch: {e}")
            return False

    def _configure_index(self):
        """Configure index settings (searchable, filterable fields)"""
        if not self.index:
            return

        try:
            # Update searchable attributes
            self.index.update_searchable_attributes(SEARCHABLE_FIELDS)

            # Update filterable attributes
            self.index.update_filterable_attributes(FILTERABLE_FIELDS)

            # Update sortable attributes
            self.index.update_sortable_attributes(SORTABLE_FIELDS)

            # Configure ranking rules
            self.index.update_ranking_rules([
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness"
            ])

            logger.info(f"Index '{INDEX_NAME}' configured successfully")

        except Exception as e:
            logger.warning(f"Failed to configure index: {e}")

    def health_check(self) -> Dict[str, Any]:
        """
        Check Meilisearch health and return status

        Returns:
            dict: Health status information
        """
        try:
            if not self.client:
                return {"status": "disconnected", "error": "Client not initialized"}

            health = self.client.health()
            stats = self.index.get_stats() if self.index else {}

            return {
                "status": health.get("status", "unknown"),
                "index": INDEX_NAME,
                "document_count": stats.get("numberOfDocuments", 0),
                "is_indexing": stats.get("isIndexing", False),
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def index_documents(self, documents: List[Any]) -> Dict[str, Any]:
        """
        Index multiple documents in Meilisearch

        Args:
            documents: List of Document objects or dictionaries

        Returns:
            dict: Task information from Meilisearch
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            # Convert Document objects to dicts if needed
            doc_dicts = []
            for doc in documents:
                if hasattr(doc, 'model_dump'):  # Pydantic model
                    doc_dicts.append(doc.model_dump())
                elif isinstance(doc, dict):
                    doc_dicts.append(doc)
                else:
                    raise ValueError(f"Invalid document type: {type(doc)}")

            task = self.index.add_documents(doc_dicts)
            logger.info(f"Indexed {len(doc_dicts)} documents, task: {task.task_uid}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to index documents: {e}")
            raise

    async def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document from the index

        Args:
            document_id: Document ID to delete

        Returns:
            dict: Task information
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            task = self.index.delete_document(document_id)
            logger.info(f"Deleted document {document_id}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            raise

    def delete_documents_by_filter(self, filter_str: str) -> Dict[str, Any]:
        """
        Delete documents matching a filter

        Args:
            filter_str: Meilisearch filter string (e.g., "source_id = 'source1'")

        Returns:
            dict: Task information
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            task = self.index.delete_documents_by_filter(filter_str)
            logger.info(f"Deleted documents with filter: {filter_str}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            raise

    async def search(
        self,
        query: str,
        filters: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search documents

        Args:
            query: Search query string
            filters: Optional Meilisearch filter string
            limit: Number of results to return
            offset: Pagination offset

        Returns:
            dict: Search results with hits, query time, etc.
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            results = self.index.search(
                query,
                {
                    "filter": filters,
                    "limit": limit,
                    "offset": offset,
                    "attributesToHighlight": ["content"],
                    "highlightPreTag": "<mark>",
                    "highlightPostTag": "</mark>",
                    "cropLength": 200,
                }
            )

            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise


# Type alias for compatibility
SearchService = MeilisearchService

# Global Meilisearch service instance
meili_service = MeilisearchService()
