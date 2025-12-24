# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Indexing service with incremental logic
Orchestrates file scanning, extraction, and Meilisearch indexing
"""
import hashlib
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Source, IndexedFile
from ..schemas import Document
from ..extractors import extractor_registry
from ..config import settings
from .scanner import FileScanner
from .search import SearchService

logger = logging.getLogger(__name__)


class IndexingStats:
    """Statistics for an indexing run"""

    def __init__(self):
        self.total_scanned = 0
        self.new_files = 0
        self.modified_files = 0
        self.unchanged_files = 0
        self.deleted_files = 0
        self.successful = 0
        self.failed = 0
        self.skipped = 0  # Unsupported file types
        self.errors: List[Dict[str, str]] = []

    def to_dict(self) -> dict:
        """Convert stats to dictionary"""
        return {
            "total_scanned": self.total_scanned,
            "new_files": self.new_files,
            "modified_files": self.modified_files,
            "unchanged_files": self.unchanged_files,
            "deleted_files": self.deleted_files,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "error_count": len(self.errors),
            "errors": self.errors[:100],  # Limit to first 100 errors
        }


class IndexingService:
    """
    Service for indexing files from a source

    Handles:
    - Incremental indexing (only changed files)
    - File scanning with glob patterns
    - Document extraction
    - Meilisearch indexing
    - Error tracking and recovery
    """

    def __init__(self, db: Session, search_service: SearchService):
        """
        Initialize indexing service

        Args:
            db: Database session
            search_service: Search service instance
        """
        self.db = db
        self.search_service = search_service

    async def index_source(self, source_id: str) -> IndexingStats:
        """
        Index or reindex a source

        Args:
            source_id: ID of source to index

        Returns:
            IndexingStats with results

        Raises:
            ValueError: If source not found
        """
        # Get source from database
        source = self.db.get(Source, source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")

        # Track timing for performance metrics
        start_time = time.time()

        logger.info(
            f"Starting indexing for source: '{source.name}' (ID: {source.id}) "
            f"at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        stats = IndexingStats()
        total_bytes_processed = 0  # Track bytes for throughput metrics

        # Clear existing documents for this source from both Meilisearch and database
        # This ensures clean reindexing and handles migration from old ID formats
        try:
            await self.search_service.delete_documents_by_filter(f"source_id = '{source_id}'")
            # Also clear indexed_files records so all files are treated as new
            from sqlalchemy import delete
            self.db.execute(delete(IndexedFile).where(IndexedFile.source_id == source_id))
            self.db.commit()
            logger.info(f"Cleared existing documents for source '{source_id}' from Meilisearch and database")
        except Exception as e:
            logger.warning(f"Failed to clear existing documents for source '{source_id}': {e}")

        try:
            # Parse include/exclude patterns
            import json
            include_patterns = json.loads(source.include_patterns) if source.include_patterns else None
            exclude_patterns = json.loads(source.exclude_patterns) if source.exclude_patterns else None

            # Scan files
            scanner = FileScanner(
                root_path=source.root_path,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns
            )

            # Get list of current files
            current_files = set()
            for file_path in scanner.scan():
                current_files.add(file_path)
                stats.total_scanned += 1

            scan_elapsed = time.time() - start_time
            logger.info(
                f"Scanned {stats.total_scanned} files for source '{source.name}' "
                f"in {scan_elapsed:.2f}s"
            )

            # Get previously indexed files for this source
            indexed_files_map = self._get_indexed_files_map(source_id)

            # Process current files
            documents_to_index = []
            files_processed = 0

            for file_path in current_files:
                files_processed += 1
                try:
                    # Check if file needs indexing
                    needs_indexing, reason = self._check_needs_indexing(
                        file_path, indexed_files_map
                    )

                    if not needs_indexing:
                        stats.unchanged_files += 1
                        logger.debug(f"Skipping unchanged file: {file_path}")
                        continue

                    # Track if this is new or modified
                    if reason == "new":
                        stats.new_files += 1
                    elif reason == "modified":
                        stats.modified_files += 1

                    # Extract document
                    document = await self._extract_document(
                        file_path, source.id, source.name
                    )

                    if document is None:
                        # File type not supported
                        stats.skipped += 1
                        logger.debug(f"Skipped unsupported file type: {file_path}")
                        self._update_indexed_file(
                            source_id, file_path, status="skipped",
                            error="Unsupported file type"
                        )
                        continue

                    # Add to batch for indexing
                    documents_to_index.append(document)
                    total_bytes_processed += document.size_bytes

                    # Update indexed_files table
                    self._update_indexed_file(
                        source_id, file_path, status="success"
                    )

                    stats.successful += 1

                    # Batch index using configurable batch size
                    if len(documents_to_index) >= settings.meilisearch_batch_size:
                        logger.debug(
                            f"Indexing batch of {len(documents_to_index)} documents "
                            f"to Meilisearch"
                        )
                        await self.search_service.index_documents(documents_to_index)
                        documents_to_index = []

                    # Progress reporting
                    if files_processed % settings.indexing_progress_interval == 0:
                        elapsed = time.time() - start_time
                        rate = files_processed / elapsed if elapsed > 0 else 0
                        logger.info(
                            f"Progress: {files_processed}/{stats.total_scanned} files processed "
                            f"({stats.successful} indexed, {stats.failed} failed, "
                            f"{stats.skipped} skipped) - {rate:.1f} files/sec"
                        )

                except Exception as e:
                    logger.warning(
                        f"Failed to index file '{Path(file_path).name}': {type(e).__name__}: {e}",
                        extra={"file_path": file_path, "error": str(e)}
                    )
                    stats.failed += 1
                    stats.errors.append({
                        "file": file_path,
                        "error": str(e)
                    })

                    # Update indexed_files with error
                    self._update_indexed_file(
                        source_id, file_path, status="failed", error=str(e)
                    )

            # Index remaining documents
            if documents_to_index:
                logger.debug(f"Indexing final batch of {len(documents_to_index)} documents")
                await self.search_service.index_documents(documents_to_index)

            # Handle deleted files (in DB but not in current scan)
            deleted_count = await self._handle_deleted_files(
                source_id, current_files, indexed_files_map
            )
            stats.deleted_files = deleted_count

            # Commit all database changes
            self.db.commit()

            # Calculate final metrics
            elapsed_time = time.time() - start_time
            files_per_sec = stats.successful / elapsed_time if elapsed_time > 0 else 0
            mb_per_sec = (total_bytes_processed / (1024 * 1024)) / elapsed_time if elapsed_time > 0 else 0

            logger.info(
                f"✓ Indexing complete for '{source.name}': "
                f"{stats.successful} successful, {stats.failed} failed, "
                f"{stats.skipped} skipped, {stats.deleted_files} deleted "
                f"({stats.unchanged_files} unchanged) | "
                f"Scanned {stats.total_scanned} files in {elapsed_time:.2f}s | "
                f"Performance: {files_per_sec:.1f} files/sec, {mb_per_sec:.2f} MB/sec"
            )

            # Log errors summary if any failures
            if stats.failed > 0:
                logger.warning(
                    f"Indexing completed with {stats.failed} failures for '{source.name}'. "
                    f"First 5 errors: {stats.errors[:5]}"
                )

        except Exception as e:
            logger.error(f"Fatal error during indexing: {e}")
            self.db.rollback()
            raise

        return stats

    def _get_indexed_files_map(self, source_id: str) -> Dict[str, IndexedFile]:
        """
        Get map of previously indexed files for a source

        Args:
            source_id: Source ID

        Returns:
            Dictionary mapping file path to IndexedFile record
        """
        stmt = select(IndexedFile).where(IndexedFile.source_id == source_id)
        indexed_files = self.db.execute(stmt).scalars().all()

        return {indexed_file.path: indexed_file for indexed_file in indexed_files}

    def _check_needs_indexing(
        self, file_path: str, indexed_files_map: Dict[str, IndexedFile]
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a file needs to be indexed

        Args:
            file_path: Path to file
            indexed_files_map: Map of previously indexed files

        Returns:
            Tuple of (needs_indexing, reason)
            reason is one of: "new", "modified", None
        """
        # Get file stats
        path = Path(file_path)
        stat = path.stat()
        size = stat.st_size
        mtime = int(stat.st_mtime)

        # Check if file was previously indexed
        if file_path not in indexed_files_map:
            return True, "new"

        indexed_file = indexed_files_map[file_path]

        # Check if file has been modified (size or mtime changed)
        # Convert both datetimes to timestamps for reliable comparison
        try:
            indexed_mtime = int(indexed_file.modified_at.timestamp()) if indexed_file.modified_at else 0
        except (OSError, OverflowError):
            # Handle edge cases like dates before 1970 on Windows
            indexed_mtime = 0

        if indexed_file.size_bytes != size or indexed_mtime != mtime:
            return True, "modified"

        # File is unchanged
        return False, None

    async def _extract_document(
        self, file_path: str, source_id: str, source_name: str
    ) -> Optional[Document]:
        """
        Extract document content using appropriate extractor

        Args:
            file_path: Path to file
            source_id: Source ID
            source_name: Source name

        Returns:
            Extracted Document or None if no suitable extractor
        """
        # Get appropriate extractor
        extractor = extractor_registry.get_extractor(
            file_path, source_id, source_name
        )

        if extractor is None:
            logger.debug(f"No extractor for file: {file_path}")
            return None

        # Extract with timeout
        document = await extractor.extract_with_timeout(file_path)

        return document

    def _update_indexed_file(
        self,
        source_id: str,
        file_path: str,
        status: str = "success",
        error: Optional[str] = None
    ):
        """
        Update or create indexed_files record

        Args:
            source_id: Source ID
            file_path: File path
            status: Status (success, failed, skipped)
            error: Error message if any
        """
        # Get file stats - handle case where file disappeared
        path = Path(file_path)
        try:
            stat = path.stat()
            size_bytes = stat.st_size
            modified_at = datetime.fromtimestamp(stat.st_mtime)
        except FileNotFoundError:
            # File was deleted between scan and now
            # Mark as failed so we can track it was attempted
            logger.warning(f"File disappeared before updating record: {file_path}")
            size_bytes = 0
            modified_at = datetime.utcnow()
            status = "failed"
            error = error or "File not found during index update"
        except (OSError, PermissionError) as e:
            # Other file access errors
            logger.warning(f"Error accessing file during update: {file_path}: {e}")
            size_bytes = 0
            modified_at = datetime.utcnow()
            status = "failed"
            error = error or f"File access error: {str(e)}"

        # Check if record exists
        stmt = select(IndexedFile).where(
            IndexedFile.source_id == source_id,
            IndexedFile.path == file_path
        )
        indexed_file = self.db.execute(stmt).scalar_one_or_none()

        if indexed_file:
            # Update existing record
            indexed_file.size_bytes = size_bytes
            indexed_file.modified_at = modified_at
            indexed_file.indexed_at = datetime.utcnow()
            indexed_file.status = status
            indexed_file.error_message = error
        else:
            # Create new record
            indexed_file = IndexedFile(
                source_id=source_id,
                path=file_path,
                size_bytes=size_bytes,
                modified_at=modified_at,
                indexed_at=datetime.utcnow(),
                status=status,
                error_message=error
            )
            self.db.add(indexed_file)

    async def _handle_deleted_files(
        self,
        source_id: str,
        current_files: set,
        indexed_files_map: Dict[str, IndexedFile]
    ) -> int:
        """
        Handle files that were indexed but no longer exist

        Args:
            source_id: Source ID
            current_files: Set of currently scanned file paths
            indexed_files_map: Map of previously indexed files

        Returns:
            Number of deleted files handled
        """
        deleted_count = 0

        for indexed_path, indexed_file in indexed_files_map.items():
            if indexed_path not in current_files:
                # File was deleted
                logger.info(f"File deleted: {indexed_path}")

                # Remove from Meilisearch using hash-based ID
                path_hash = hashlib.sha256(indexed_path.encode()).hexdigest()[:12]
                doc_id = f"{source_id}--{path_hash}"
                await self.search_service.delete_document(doc_id)

                # Remove from database
                self.db.delete(indexed_file)

                deleted_count += 1

        return deleted_count

    def get_source_status(self, source_id: str) -> Dict[str, Any]:
        """
        Get indexing status for a source

        Args:
            source_id: Source ID

        Returns:
            Dictionary with status information
        """
        # Get source
        source = self.db.get(Source, source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")

        # Get indexed files stats
        stmt = select(IndexedFile).where(IndexedFile.source_id == source_id)
        indexed_files = self.db.execute(stmt).scalars().all()

        total_files = len(indexed_files)
        successful = sum(1 for f in indexed_files if f.status == "success")
        failed = sum(1 for f in indexed_files if f.status == "failed")
        skipped = sum(1 for f in indexed_files if f.status == "skipped")

        # Get last indexed time
        last_indexed = None
        if indexed_files:
            last_indexed = max(f.indexed_at for f in indexed_files)

        # Get failed files
        failed_files = [
            {"path": f.path, "error": f.error_message}
            for f in indexed_files if f.status == "failed"
        ]

        return {
            "source_id": source.id,
            "source_name": source.name,
            "total_files": total_files,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "last_indexed_at": last_indexed,
            "failed_files": failed_files[:50],  # Limit to 50
        }
