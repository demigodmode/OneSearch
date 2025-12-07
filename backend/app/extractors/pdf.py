"""
PDF file extractor with metadata extraction
Handles text extraction from PDF documents with robust error handling
"""
from pathlib import Path
from typing import Optional
import PyPDF2
import io

from .base import BaseExtractor, extractor_registry
from ..schemas import Document
from ..config import settings


class PDFExtractor(BaseExtractor):
    """
    Extractor for PDF files

    Supports:
    - .pdf - PDF documents
    - Text extraction from all pages
    - Metadata extraction (title, author, page count, etc.)
    - Fallback strategy on extraction failures
    """

    SUPPORTED_EXTENSIONS = ['.pdf']

    # Max file size from settings
    MAX_FILE_SIZE = settings.max_pdf_file_size_mb * 1024 * 1024

    # Timeout from settings
    TIMEOUT = settings.pdf_extraction_timeout

    async def extract(self, file_path: str) -> Document:
        """
        Extract text and metadata from PDF file

        Args:
            file_path: Path to PDF file

        Returns:
            Document with extracted content

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large
            Exception: For other PDF extraction errors
        """
        # Check file size
        size_bytes = self._check_file_size(file_path)

        # Extract text and metadata from PDF
        try:
            content, metadata = self._extract_pdf_content(file_path)
        except Exception as e:
            # Fallback: Create document with minimal content on extraction failure
            # This allows the file to still be indexed by filename
            content = ""
            metadata = {
                "extraction_error": str(e),
                "extraction_failed": True,
            }

        # Create base document
        doc = self._create_base_document(file_path, content)

        # Set title from metadata or filename
        doc.title = metadata.get("title") or Path(file_path).stem

        # Add PDF metadata
        doc.metadata = metadata

        return doc

    def _extract_pdf_content(self, file_path: str) -> tuple[str, dict]:
        """
        Extract text content and metadata from PDF

        Args:
            file_path: Path to PDF file

        Returns:
            Tuple of (extracted_text, metadata_dict)

        Raises:
            Exception: Various PDF-related exceptions
        """
        metadata = {}
        extracted_text_parts = []

        # Open PDF file
        with open(file_path, 'rb') as f:
            # Create PDF reader
            try:
                pdf_reader = PyPDF2.PdfReader(f)
            except Exception as e:
                raise ValueError(f"Failed to open PDF: {str(e)}")

            # Check if PDF is encrypted
            if pdf_reader.is_encrypted:
                # Try to decrypt with empty password
                try:
                    pdf_reader.decrypt('')
                except Exception:
                    raise ValueError("PDF is encrypted and cannot be decrypted")

            # Get number of pages
            num_pages = len(pdf_reader.pages)
            metadata["page_count"] = num_pages

            # Extract metadata from PDF info
            if pdf_reader.metadata:
                pdf_info = pdf_reader.metadata
                if pdf_info.title:
                    metadata["title"] = str(pdf_info.title)
                if pdf_info.author:
                    metadata["author"] = str(pdf_info.author)
                if pdf_info.subject:
                    metadata["subject"] = str(pdf_info.subject)
                if pdf_info.creator:
                    metadata["creator"] = str(pdf_info.creator)
                if pdf_info.producer:
                    metadata["producer"] = str(pdf_info.producer)

            # Extract text from each page
            for page_num in range(num_pages):
                try:
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()

                    if page_text:
                        extracted_text_parts.append(page_text)
                except Exception as e:
                    # Log page extraction failure but continue
                    metadata[f"page_{page_num}_error"] = str(e)
                    continue

        # Combine all text
        full_text = "\n\n".join(extracted_text_parts)

        # Add extraction stats
        metadata["extracted_text_length"] = len(full_text)
        metadata["pages_extracted"] = len(extracted_text_parts)
        metadata["extraction_failed"] = False

        # Check if we got any text
        if not full_text.strip():
            metadata["extraction_warning"] = "No text extracted (might be image-based PDF)"

        return full_text, metadata

    def _get_document_type(self) -> str:
        """Return 'pdf' as document type"""
        return "pdf"


# Register this extractor
extractor_registry.register(PDFExtractor)
