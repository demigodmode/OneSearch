# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Markdown file extractor with YAML front-matter support
Extracts content and metadata from markdown documents
"""
import logging
import frontmatter
from pathlib import Path
from typing import Dict, Any

from .base import BaseExtractor, extractor_registry
from ..schemas import Document
from ..config import settings

logger = logging.getLogger(__name__)


class MarkdownExtractor(BaseExtractor):
    """
    Extractor for Markdown files

    Supports:
    - .md, .markdown - Markdown files
    - YAML front-matter parsing
    - Title extraction from # heading or front-matter
    """

    SUPPORTED_EXTENSIONS = ['.md', '.markdown', '.mdown', '.mkd']

    # Max file size from settings
    MAX_FILE_SIZE = settings.max_text_file_size_mb * 1024 * 1024

    # Timeout from settings
    TIMEOUT = settings.text_extraction_timeout

    def extract(self, file_path: str) -> Document:
        """
        Extract markdown content and parse YAML front-matter

        Args:
            file_path: Path to markdown file

        Returns:
            Document with extracted content (may have minimal content on extraction failure)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large (hard failure - file should be skipped)
        """
        # Check file size first (hard failure - we don't index oversized files)
        try:
            size_bytes = self._check_file_size(file_path)
        except (FileNotFoundError, ValueError) as e:
            # These are hard failures - don't try to recover
            logger.warning(f"Markdown file check failed for {file_path}: {e}")
            raise

        # Try extraction with graceful fallback on parsing errors
        try:
            # Parse markdown with front-matter
            post, content, metadata = self._parse_markdown(file_path)

            # Create base document
            doc = self._create_base_document(file_path, content)

            # Extract title from front-matter or first heading
            doc.title = self._extract_title(post, content, file_path)

            # Add front-matter metadata
            metadata["extraction_failed"] = False
            doc.metadata = metadata

            return doc

        except UnicodeDecodeError as e:
            # Graceful fallback: Index by filename only
            logger.warning(
                f"Markdown file encoding error for {file_path}: {e}. File will be indexed by filename only.",
                extra={"file_path": file_path, "error": str(e)}
            )
            # Create minimal document
            doc = self._create_base_document(file_path, "")
            doc.title = Path(file_path).stem
            doc.metadata = {
                "extraction_error": str(e),
                "extraction_failed": True,
            }
            return doc

        except Exception as e:
            # Graceful fallback for unexpected errors (e.g., invalid YAML front-matter)
            logger.warning(
                f"Unexpected error extracting markdown from {file_path}: {e}. File will be indexed by filename only.",
                extra={"file_path": file_path, "error": str(e)},
                exc_info=True
            )
            # Create minimal document
            doc = self._create_base_document(file_path, "")
            doc.title = Path(file_path).stem
            doc.metadata = {
                "extraction_error": str(e),
                "extraction_failed": True,
            }
            return doc

    def _parse_markdown(self, file_path: str) -> tuple[Any, str, Dict[str, Any]]:
        """
        Parse markdown file with YAML front-matter

        Args:
            file_path: Path to markdown file

        Returns:
            Tuple of (frontmatter.Post, content_text, metadata_dict)
        """
        # Try UTF-8 first
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                post = frontmatter.load(f)
        except UnicodeDecodeError:
            # Fallback to latin-1
            with open(file_path, 'r', encoding='latin-1') as f:
                post = frontmatter.load(f)

        # Extract content (without front-matter)
        content = post.content

        # Extract metadata from front-matter
        metadata = {
            "has_frontmatter": len(post.metadata) > 0,
            "frontmatter": dict(post.metadata),
        }

        # Add common front-matter fields to top-level metadata
        if "tags" in post.metadata:
            metadata["tags"] = post.metadata["tags"]
        if "date" in post.metadata:
            metadata["date"] = str(post.metadata["date"])
        if "author" in post.metadata:
            metadata["author"] = post.metadata["author"]
        if "description" in post.metadata:
            metadata["description"] = post.metadata["description"]

        return post, content, metadata

    def _extract_title(self, post: Any, content: str, file_path: str) -> str:
        """
        Extract title from markdown file

        Priority:
        1. 'title' field in YAML front-matter
        2. First # heading in content
        3. Filename without extension

        Args:
            post: frontmatter.Post object
            content: Markdown content (without front-matter)
            file_path: Path to file

        Returns:
            Extracted title
        """
        # Check front-matter for title
        if "title" in post.metadata:
            title = str(post.metadata["title"]).strip()
            if title:
                return title

        # Look for first # heading
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('# '):
                # Extract heading text (remove # and clean up)
                title = line.lstrip('#').strip()
                if title:
                    return title

        # Fallback to filename
        path = Path(file_path)
        return path.stem

    def _get_document_type(self) -> str:
        """Return 'markdown' as document type"""
        return "markdown"


# Register this extractor
extractor_registry.register(MarkdownExtractor)
