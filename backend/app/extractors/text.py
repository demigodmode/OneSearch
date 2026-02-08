# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Text file extractor for plain text documents
Supports various text-based file formats with encoding detection
"""
import logging
import chardet
from pathlib import Path

from .base import BaseExtractor, extractor_registry
from ..schemas import Document
from ..config import settings

logger = logging.getLogger(__name__)


class TextExtractor(BaseExtractor):
    """
    Extractor for plain text files

    Supports:
    - .txt - Plain text files
    - .log - Log files
    - .conf, .cfg, .ini - Configuration files
    - .env.example - Environment example files
    - .sh, .bash - Shell scripts
    - .py, .js, .ts, .java, .c, .cpp, .h - Source code files
    """

    SUPPORTED_EXTENSIONS = [
        '.txt', '.text',
        '.log',
        '.conf', '.cfg', '.config', '.ini',
        '.env.example',
        '.sh', '.bash', '.zsh',
        '.py', '.pyw',
        '.js', '.jsx', '.ts', '.tsx',
        '.java', '.c', '.cpp', '.cc', '.h', '.hpp',
        '.go', '.rs', '.rb', '.php',
        '.css', '.scss', '.sass', '.less',
        '.html', '.htm', '.xml', '.json', '.yaml', '.yml',
        '.sql', '.r'
    ]

    # Max file size from settings
    MAX_FILE_SIZE = settings.max_text_file_size_mb * 1024 * 1024

    # Timeout from settings
    TIMEOUT = settings.text_extraction_timeout

    def extract(self, file_path: str) -> Document:
        """
        Extract text content from file with encoding detection (synchronous)
        This runs in a thread pool to allow timeout interruption

        Args:
            file_path: Path to text file

        Returns:
            Document with extracted text content (may have minimal content on extraction failure)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large (hard failure - file should be skipped)
        """
        # Check file size first (hard failure - we don't index oversized files)
        try:
            size_bytes = self._check_file_size(file_path)
        except (FileNotFoundError, ValueError) as e:
            # These are hard failures - don't try to recover
            logger.warning(f"Text file check failed for {file_path}: {e}")
            raise

        # Try extraction with graceful fallback on encoding errors
        try:
            # Read file content with encoding detection
            content, detected_encoding = self._read_with_encoding_detection(file_path)

            # Create base document
            doc = self._create_base_document(file_path, content)

            # Try to extract title from first line (for code files, config files)
            doc.title = self._extract_title(file_path, content)

            # Add metadata
            doc.metadata = {
                "detected_encoding": detected_encoding,
                "line_count": content.count('\n') + 1,
                "extraction_failed": False,
            }

            return doc

        except UnicodeDecodeError as e:
            # Graceful fallback: Index by filename only
            logger.warning(
                f"Text file encoding error for {file_path}: {e}. File will be indexed by filename only.",
                extra={"file_path": file_path, "error": str(e)}
            )
            # Create minimal document with just filename
            doc = self._create_base_document(file_path, "")
            doc.title = Path(file_path).stem
            doc.metadata = {
                "extraction_error": str(e),
                "extraction_failed": True,
            }
            return doc

        except Exception as e:
            # Graceful fallback for unexpected errors
            logger.warning(
                f"Unexpected error extracting text from {file_path}: {e}. File will be indexed by filename only.",
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

    def _read_with_encoding_detection(self, file_path: str) -> tuple[str, str]:
        """
        Read file content with automatic encoding detection

        Args:
            file_path: Path to file

        Returns:
            Tuple of (decoded text content, detected encoding name)

        Raises:
            UnicodeDecodeError: If file cannot be decoded
        """
        # Try UTF-8 first (most common)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read(), 'utf-8'
        except UnicodeDecodeError:
            pass

        # Detect encoding using chardet
        detected_encoding = self._detect_encoding(file_path)

        # Try detected encoding
        try:
            with open(file_path, 'r', encoding=detected_encoding) as f:
                return f.read(), detected_encoding
        except (UnicodeDecodeError, TypeError):
            # Fallback to latin-1 (never fails but may produce garbage)
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read(), 'latin-1'

    def _detect_encoding(self, file_path: str) -> str:
        """
        Detect file encoding using chardet

        Args:
            file_path: Path to file

        Returns:
            Detected encoding (e.g., 'utf-8', 'ascii', 'iso-8859-1')
        """
        with open(file_path, 'rb') as f:
            # Read first 10KB for detection (faster than full file)
            raw_data = f.read(10240)

        result = chardet.detect(raw_data)
        encoding = result.get('encoding', 'utf-8')

        # Fallback to utf-8 if detection failed
        return encoding or 'utf-8'

    def _extract_title(self, file_path: str, content: str) -> str:
        """
        Extract title from file

        For text files, use:
        1. First non-empty line (up to 100 chars)
        2. Filename if first line is too long

        Args:
            file_path: Path to file
            content: File content

        Returns:
            Extracted title or filename
        """
        path = Path(file_path)

        # Try to get first non-empty line
        lines = content.split('\n')
        for line in lines[:5]:  # Check first 5 lines
            line = line.strip()
            if line and len(line) <= 100:
                # Remove common comment markers
                for prefix in ['#', '//', '/*', '--', '<!--']:
                    if line.startswith(prefix):
                        line = line[len(prefix):].strip()
                if line:
                    return line

        # Fallback to filename without extension
        return path.stem


# Register this extractor
extractor_registry.register(TextExtractor)
