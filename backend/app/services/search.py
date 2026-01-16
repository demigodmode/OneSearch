# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Meilisearch client wrapper and document indexing
"""
import asyncio
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

            # Try to get existing index, or create it if it doesn't exist
            try:
                self.index = self.client.get_index(INDEX_NAME)
                logger.info(f"Found existing index '{INDEX_NAME}'")
            except Exception:
                # Index doesn't exist, create it
                logger.info(f"Creating index '{INDEX_NAME}'...")
                task = self.client.create_index(INDEX_NAME, {"primaryKey": "id"})
                # Wait for index creation to complete
                self.client.wait_for_task(task.task_uid, timeout_in_ms=30000)
                self.index = self.client.get_index(INDEX_NAME)
                logger.info(f"Created index '{INDEX_NAME}'")

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
            stats = self.index.get_stats() if self.index else None

            # Handle both dict and object responses from meilisearch client
            health_status = health.get("status", "unknown") if isinstance(health, dict) else getattr(health, "status", "available")

            doc_count = 0
            is_indexing = False
            if stats:
                doc_count = stats.get("numberOfDocuments", 0) if isinstance(stats, dict) else getattr(stats, "number_of_documents", 0)
                is_indexing = stats.get("isIndexing", False) if isinstance(stats, dict) else getattr(stats, "is_indexing", False)

            return {
                "status": health_status,
                "index": INDEX_NAME,
                "document_count": doc_count,
                "is_indexing": is_indexing,
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def index_documents(self, documents: List[Any]) -> Dict[str, Any]:
        """
        Index multiple documents in Meilisearch (runs in thread pool)

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

            # Run blocking HTTP call in thread pool
            task = await asyncio.to_thread(self.index.add_documents, doc_dicts)
            logger.info(f"Indexed {len(doc_dicts)} documents, task: {task.task_uid}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to index documents: {e}")
            raise

    async def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document from the index (runs in thread pool)

        Args:
            document_id: Document ID to delete

        Returns:
            dict: Task information
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            # Run blocking HTTP call in thread pool
            task = await asyncio.to_thread(self.index.delete_document, document_id)
            logger.info(f"Deleted document {document_id}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            raise

    async def delete_documents_by_filter(self, filter_str: str) -> Dict[str, Any]:
        """
        Delete documents matching a filter (runs in thread pool)

        Args:
            filter_str: Meilisearch filter string (e.g., "source_id = 'source1'")

        Returns:
            dict: Task information
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            # Run blocking HTTP call in thread pool
            task = await asyncio.to_thread(
                self.index.delete_documents_by_filter, filter_str
            )
            logger.info(f"Deleted documents with filter: {filter_str}")
            return task.__dict__

        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            raise

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single document by ID (runs in thread pool)

        Args:
            document_id: Document ID to retrieve

        Returns:
            dict: Document data or None if not found
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            # Run blocking HTTP call in thread pool
            document = await asyncio.to_thread(self.index.get_document, document_id)
            return document
        except meilisearch.errors.MeilisearchApiError as e:
            if "document_not_found" in str(e).lower() or e.code == "document_not_found":
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get document {document_id}: {e}")
            raise

    async def search(
        self,
        query: str,
        filters: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search documents (runs blocking Meilisearch HTTP call in thread pool)

        Args:
            query: Search query string
            filters: Optional list of Meilisearch filter strings (safer than single string)
            limit: Number of results to return
            offset: Pagination offset

        Returns:
            dict: Search results with hits, query time, etc.
        """
        if not self.index:
            raise RuntimeError("Index not initialized")

        try:
            # Run blocking Meilisearch HTTP call in thread pool to avoid blocking event loop
            results = await asyncio.to_thread(
                self.index.search,
                query,
                {
                    "filter": filters,  # Can be string or array
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
