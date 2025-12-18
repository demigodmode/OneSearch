# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Base extractor interface for document extraction
All extractors must inherit from BaseExtractor
"""
import asyncio
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from ..schemas import Document


class BaseExtractor(ABC):
    """
    Abstract base class for document extractors

    Each extractor handles specific file types and implements
    the extract() method to convert files into normalized Documents
    """

    # File extensions this extractor supports (e.g., ['.txt', '.log'])
    SUPPORTED_EXTENSIONS: List[str] = []

    # Maximum file size in bytes (can be overridden per extractor)
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB default

    # Extraction timeout in seconds
    TIMEOUT: int = 5

    def __init__(self, source_id: str, source_name: str):
        """
        Initialize extractor

        Args:
            source_id: ID of the source this file belongs to
            source_name: Name of the source for display
        """
        self.source_id = source_id
        self.source_name = source_name

    @abstractmethod
    def extract(self, file_path: str) -> Document:
        """
        Extract content from a file and return normalized Document (synchronous)

        This method performs blocking I/O and will be run in a thread pool
        by extract_with_timeout() to enable timeout interruption.

        Args:
            file_path: Absolute path to the file

        Returns:
            Document with extracted content and metadata

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large or invalid format
            Exception: For other extraction errors
        """
        pass

    async def extract_with_timeout(self, file_path: str) -> Document:
        """
        Extract with timeout protection

        Runs the synchronous extract() in a thread pool so that
        asyncio.wait_for can properly timeout blocking I/O operations.

        Args:
            file_path: Absolute path to the file

        Returns:
            Document with extracted content

        Raises:
            TimeoutError: If extraction exceeds timeout
        """
        try:
            # Run extraction in a thread pool to ensure blocking I/O can be interrupted
            return await asyncio.wait_for(
                asyncio.to_thread(self.extract, file_path),
                timeout=self.TIMEOUT
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Extraction timed out after {self.TIMEOUT}s for {file_path}"
            )

    def _check_file_size(self, file_path: str) -> int:
        """
        Check if file size is within limits

        Args:
            file_path: Path to file

        Returns:
            File size in bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file exceeds size limit
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        size = path.stat().st_size

        if size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE / (1024 * 1024)
            actual_mb = size / (1024 * 1024)
            raise ValueError(
                f"File too large: {actual_mb:.2f}MB (max: {max_mb:.2f}MB)"
            )

        return size

    def _get_file_metadata(self, file_path: str) -> dict:
        """
        Get basic file metadata (size, modified time, etc.)

        Args:
            file_path: Path to file

        Returns:
            Dictionary with metadata
        """
        path = Path(file_path)
        stat = path.stat()

        return {
            "size_bytes": stat.st_size,
            "modified_at": int(stat.st_mtime),
            "basename": path.name,
            "extension": path.suffix.lower().lstrip('.'),
            "path": str(path.absolute()),
        }

    def _compute_file_hash(self, file_path: str) -> str:
        """
        Compute SHA256 hash of file content

        Args:
            file_path: Path to file

        Returns:
            Hex digest of file hash
        """
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            # Read in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    def _create_document_id(self, file_path: str) -> str:
        """
        Create unique document ID for Meilisearch

        Format: "source_id:/path/to/file"

        Args:
            file_path: Path to file

        Returns:
            Unique document ID
        """
        return f"{self.source_id}:{file_path}"

    def _create_base_document(self, file_path: str, content: str) -> Document:
        """
        Create base Document with common fields populated

        Args:
            file_path: Path to file
            content: Extracted text content

        Returns:
            Document with base fields populated
        """
        metadata = self._get_file_metadata(file_path)

        return Document(
            id=self._create_document_id(file_path),
            source_id=self.source_id,
            source_name=self.source_name,
            path=metadata["path"],
            basename=metadata["basename"],
            extension=metadata["extension"],
            type=self._get_document_type(),
            size_bytes=metadata["size_bytes"],
            modified_at=metadata["modified_at"],
            indexed_at=int(datetime.utcnow().timestamp()),
            content=content,
            title=None,
            metadata={}
        )

    def _get_document_type(self) -> str:
        """
        Get document type string for this extractor
        Default implementation uses class name without 'Extractor' suffix

        Returns:
            Document type (e.g., 'text', 'pdf', 'markdown')
        """
        class_name = self.__class__.__name__
        if class_name.endswith('Extractor'):
            class_name = class_name[:-9]  # Remove 'Extractor'
        return class_name.lower()

    @classmethod
    def supports_file(cls, file_path: str) -> bool:
        """
        Check if this extractor supports the given file

        Args:
            file_path: Path to file

        Returns:
            True if this extractor can handle this file type
        """
        path = Path(file_path)
        extension = path.suffix.lower()
        return extension in cls.SUPPORTED_EXTENSIONS


class ExtractorRegistry:
    """
    Registry for managing available extractors
    Automatically selects appropriate extractor based on file type
    """

    def __init__(self):
        self._extractors: List[type[BaseExtractor]] = []

    def register(self, extractor_class: type[BaseExtractor]):
        """Register an extractor class"""
        if not issubclass(extractor_class, BaseExtractor):
            raise TypeError(f"{extractor_class} must inherit from BaseExtractor")
        self._extractors.append(extractor_class)

    def get_extractor(self, file_path: str, source_id: str, source_name: str) -> Optional[BaseExtractor]:
        """
        Get appropriate extractor for a file

        Args:
            file_path: Path to file
            source_id: Source ID
            source_name: Source name

        Returns:
            Extractor instance or None if no suitable extractor found
        """
        for extractor_class in self._extractors:
            if extractor_class.supports_file(file_path):
                return extractor_class(source_id, source_name)
        return None

    def get_supported_extensions(self) -> List[str]:
        """Get list of all supported file extensions"""
        extensions = set()
        for extractor_class in self._extractors:
            extensions.update(extractor_class.SUPPORTED_EXTENSIONS)
        return sorted(list(extensions))


# Global registry instance
extractor_registry = ExtractorRegistry()
