"""
Tests for document extractors
"""
import pytest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from pypdf import PdfWriter

from app.extractors import (
    TextExtractor,
    MarkdownExtractor,
    PDFExtractor,
    extractor_registry,
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files"""
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_text_file(temp_dir):
    """Create sample text file"""
    file_path = temp_dir / "sample.txt"
    file_path.write_text("This is a test file.\nIt has multiple lines.\nFor testing purposes.")
    return str(file_path)


@pytest.fixture
def sample_markdown_file(temp_dir):
    """Create sample markdown file with front-matter"""
    file_path = temp_dir / "sample.md"
    content = """---
title: Test Document
tags: [test, markdown]
author: Test Author
---

# Main Heading

This is the content of the markdown file.

## Subheading

More content here.
"""
    file_path.write_text(content)
    return str(file_path)


@pytest.fixture
def sample_pdf_file(temp_dir):
    """Create sample PDF file"""
    file_path = temp_dir / "sample.pdf"

    # Create a simple PDF with PyPDF2
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    # Add metadata
    writer.add_metadata({
        "/Title": "Test PDF Document",
        "/Author": "Test Author",
    })

    with open(file_path, "wb") as f:
        writer.write(f)

    return str(file_path)


class TestTextExtractor:
    """Tests for TextExtractor"""

    @pytest.mark.asyncio
    async def test_extract_text_file(self, sample_text_file):
        """Test extracting from a plain text file"""
        extractor = TextExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(sample_text_file)

        assert doc.source_id == "test_source"
        assert doc.source_name == "Test Source"
        assert doc.type == "text"
        assert doc.basename == "sample.txt"
        assert doc.extension == "txt"
        assert "This is a test file" in doc.content
        assert doc.metadata["line_count"] == 3
        assert doc.title is not None

    @pytest.mark.asyncio
    async def test_supports_file(self, temp_dir):
        """Test file extension support"""
        assert TextExtractor.supports_file(str(temp_dir / "test.txt"))
        assert TextExtractor.supports_file(str(temp_dir / "test.log"))
        assert TextExtractor.supports_file(str(temp_dir / "test.py"))
        assert not TextExtractor.supports_file(str(temp_dir / "test.pdf"))

    @pytest.mark.asyncio
    async def test_file_size_limit(self, temp_dir):
        """Test file size limit enforcement"""
        # Create large file
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * (11 * 1024 * 1024))  # 11 MB

        extractor = TextExtractor("test_source", "Test Source")

        with pytest.raises(ValueError, match="File too large"):
            await extractor.extract_with_timeout(str(large_file))

    @pytest.mark.asyncio
    async def test_encoding_detection(self, temp_dir):
        """Test encoding detection for non-UTF8 files"""
        # Create file with latin-1 encoding
        latin1_file = temp_dir / "latin1.txt"
        with open(latin1_file, "w", encoding="latin-1") as f:
            f.write("Test with special chars: \xe9\xe8")

        extractor = TextExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(str(latin1_file))

        assert doc.content is not None
        assert len(doc.content) > 0

    @pytest.mark.asyncio
    async def test_timeout(self, temp_dir, monkeypatch):
        """Test extraction timeout"""
        import time

        # Create a mock extract that does blocking I/O for too long
        def slow_extract(self, file_path):
            time.sleep(10)  # Blocking sleep
            return None

        monkeypatch.setattr(TextExtractor, "extract", slow_extract)

        extractor = TextExtractor("test_source", "Test Source")
        extractor.TIMEOUT = 1  # 1 second timeout

        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        with pytest.raises(TimeoutError):
            await extractor.extract_with_timeout(str(test_file))


class TestMarkdownExtractor:
    """Tests for MarkdownExtractor"""

    @pytest.mark.asyncio
    async def test_extract_markdown_with_frontmatter(self, sample_markdown_file):
        """Test extracting markdown with YAML front-matter"""
        extractor = MarkdownExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(sample_markdown_file)

        assert doc.source_id == "test_source"
        assert doc.type == "markdown"
        assert doc.title == "Test Document"
        assert "Main Heading" in doc.content
        assert doc.metadata["has_frontmatter"] is True
        assert doc.metadata["tags"] == ["test", "markdown"]
        assert doc.metadata["author"] == "Test Author"

    @pytest.mark.asyncio
    async def test_extract_markdown_without_frontmatter(self, temp_dir):
        """Test extracting markdown without front-matter"""
        file_path = temp_dir / "no_frontmatter.md"
        file_path.write_text("# Title from Heading\n\nContent here.")

        extractor = MarkdownExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(str(file_path))

        assert doc.title == "Title from Heading"
        assert doc.metadata["has_frontmatter"] is False

    @pytest.mark.asyncio
    async def test_markdown_fallback_title(self, temp_dir):
        """Test fallback to filename for title"""
        file_path = temp_dir / "my_document.md"
        file_path.write_text("Just some content without a heading.")

        extractor = MarkdownExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(str(file_path))

        assert doc.title == "my_document"

    @pytest.mark.asyncio
    async def test_supports_file(self, temp_dir):
        """Test file extension support"""
        assert MarkdownExtractor.supports_file(str(temp_dir / "test.md"))
        assert MarkdownExtractor.supports_file(str(temp_dir / "test.markdown"))
        assert not MarkdownExtractor.supports_file(str(temp_dir / "test.txt"))


class TestPDFExtractor:
    """Tests for PDFExtractor"""

    @pytest.mark.asyncio
    async def test_extract_pdf(self, sample_pdf_file):
        """Test extracting from PDF file"""
        extractor = PDFExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(sample_pdf_file)

        assert doc.source_id == "test_source"
        assert doc.type == "pdf"
        assert doc.basename == "sample.pdf"
        assert doc.extension == "pdf"
        assert doc.metadata["page_count"] == 1
        assert doc.metadata.get("title") == "Test PDF Document"

    @pytest.mark.asyncio
    async def test_supports_file(self, temp_dir):
        """Test file extension support"""
        assert PDFExtractor.supports_file(str(temp_dir / "test.pdf"))
        assert not PDFExtractor.supports_file(str(temp_dir / "test.txt"))

    @pytest.mark.asyncio
    async def test_corrupted_pdf_fallback(self, temp_dir):
        """Test fallback behavior on corrupted PDF"""
        # Create invalid PDF file
        corrupted_pdf = temp_dir / "corrupted.pdf"
        corrupted_pdf.write_text("This is not a PDF file")

        extractor = PDFExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(str(corrupted_pdf))

        # Should still create document with minimal content
        assert doc is not None
        assert doc.content == ""
        assert doc.metadata.get("extraction_failed") is True
        assert "extraction_error" in doc.metadata

    @pytest.mark.asyncio
    async def test_encrypted_pdf(self, temp_dir):
        """Test handling of encrypted PDF that cannot be decrypted"""
        # Create encrypted PDF
        from pypdf import PdfWriter, PdfReader

        encrypted_pdf = temp_dir / "encrypted.pdf"

        # Create and encrypt a PDF
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt(user_password="password123", owner_password="password456")

        with open(encrypted_pdf, "wb") as f:
            writer.write(f)

        extractor = PDFExtractor("test_source", "Test Source")
        doc = await extractor.extract_with_timeout(str(encrypted_pdf))

        # Should handle gracefully with error in metadata
        assert doc is not None
        assert doc.metadata.get("extraction_failed") is True
        error_msg = doc.metadata.get("extraction_error", "").lower()
        # pypdf returns "file has not been decrypted" for encrypted PDFs
        assert "decrypt" in error_msg or "encrypted" in error_msg


class TestExtractorRegistry:
    """Tests for ExtractorRegistry"""

    def test_get_extractor_for_text(self, temp_dir):
        """Test getting extractor for text file"""
        file_path = temp_dir / "test.txt"
        extractor = extractor_registry.get_extractor(
            str(file_path), "source1", "Source 1"
        )

        assert extractor is not None
        assert isinstance(extractor, TextExtractor)

    def test_get_extractor_for_markdown(self, temp_dir):
        """Test getting extractor for markdown file"""
        file_path = temp_dir / "test.md"
        extractor = extractor_registry.get_extractor(
            str(file_path), "source1", "Source 1"
        )

        assert extractor is not None
        assert isinstance(extractor, MarkdownExtractor)

    def test_get_extractor_for_pdf(self, temp_dir):
        """Test getting extractor for PDF file"""
        file_path = temp_dir / "test.pdf"
        extractor = extractor_registry.get_extractor(
            str(file_path), "source1", "Source 1"
        )

        assert extractor is not None
        assert isinstance(extractor, PDFExtractor)

    def test_get_extractor_unsupported(self, temp_dir):
        """Test getting extractor for unsupported file type"""
        file_path = temp_dir / "test.docx"
        extractor = extractor_registry.get_extractor(
            str(file_path), "source1", "Source 1"
        )

        assert extractor is None

    def test_get_supported_extensions(self):
        """Test getting list of supported extensions"""
        extensions = extractor_registry.get_supported_extensions()

        assert ".txt" in extensions
        assert ".md" in extensions
        assert ".pdf" in extensions
        assert len(extensions) > 10  # Should have many supported types
