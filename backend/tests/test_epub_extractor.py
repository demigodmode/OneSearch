# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for EPUB extraction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import app.extractors.epub as epub_module
from app.extractors import EPUBExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_epub(
    path: Path,
    *,
    opf_path: str = "OEBPS/content.opf",
    include_image_spine: bool = False,
    chapter1_body: str = "Hello <em>ebook</em> world.",
) -> None:
    container_xml = f"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Example Book</dc:title>
    <dc:creator>Jane Writer</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Small Press</dc:publisher>
    <dc:date>2024-01-02</dc:date>
    <dc:identifier id="bookid">urn:isbn:1234567890</dc:identifier>
  </metadata>
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter2" href="text/chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="images/cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
    {image_spine}
  </spine>
</package>
""".format(image_spine='<itemref idref="cover"/>' if include_image_spine else '')
    chapter1 = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter One</h1><p>{chapter1_body}</p></body></html>
"""
    chapter2 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Second chapter &amp; more text.</p></body></html>
"""
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr(opf_path, opf)
        zf.writestr("OEBPS/chapter1.xhtml", chapter1)
        zf.writestr("OEBPS/text/chapter2.xhtml", chapter2)
        zf.writestr("OEBPS/images/cover.jpg", b"not really a jpeg")


@pytest.mark.asyncio
async def test_extract_epub_metadata_and_spine_text(temp_dir):
    file_path = temp_dir / "book.epub"
    write_epub(file_path)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.title == "Example Book"
    assert "Example Book" in doc.content
    assert "Jane Writer" in doc.content
    assert "Chapter One" in doc.content
    assert "Hello ebook world." in doc.content
    assert "Second chapter & more text." in doc.content
    assert doc.content.index("Chapter One") < doc.content.index("Second chapter")
    assert doc.metadata["title"] == "Example Book"
    assert doc.metadata["creator"] == "Jane Writer"
    assert doc.metadata["language"] == "en"
    assert doc.metadata["publisher"] == "Small Press"
    assert doc.metadata["date"] == "2024-01-02"
    assert doc.metadata["identifier"] == "urn:isbn:1234567890"
    assert doc.metadata["chapter_count"] == 2
    assert doc.metadata["extraction_failed"] is False


@pytest.mark.asyncio
async def test_epub_skips_non_text_spine_items(temp_dir):
    file_path = temp_dir / "book-with-cover.epub"
    write_epub(file_path, include_image_spine=True)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.metadata["chapter_count"] == 2
    assert "not really a jpeg" not in doc.content
    assert "Chapter One" in doc.content
    assert "Second chapter" in doc.content


@pytest.mark.asyncio
async def test_epub_compressed_chapter_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(epub_module, "_MAX_EPUB_CHAPTER_BYTES", 64, raising=False)
    monkeypatch.setattr(epub_module, "_MAX_EPUB_TOTAL_CHAPTER_BYTES", 10 * 1024, raising=False)
    file_path = temp_dir / "compressed-chapter.epub"
    write_epub(file_path, chapter1_body="A" * 1024)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.title == "compressed-chapter"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "EPUB archive entry too large" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_epub_total_chapter_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(epub_module, "_MAX_EPUB_CHAPTER_BYTES", 10 * 1024, raising=False)
    monkeypatch.setattr(epub_module, "_MAX_EPUB_TOTAL_CHAPTER_BYTES", 128, raising=False)
    file_path = temp_dir / "too-much-chapter-text.epub"
    write_epub(file_path, chapter1_body="A" * 1024)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "EPUB archive chapter content too large" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_epub_container_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(epub_module, "_MAX_EPUB_CONTROL_ENTRY_BYTES", 64, raising=False)
    file_path = temp_dir / "oversized-container.epub"
    write_epub(file_path)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "META-INF/container.xml" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_epub_opf_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(epub_module, "_MAX_EPUB_CONTROL_ENTRY_BYTES", 256, raising=False)
    file_path = temp_dir / "oversized-opf.epub"
    write_epub(file_path)

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "OEBPS/content.opf" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_epub_uses_epub_specific_size_limit(temp_dir):
    file_path = temp_dir / "large.epub"
    with file_path.open("wb") as f:
        f.seek((2 * 1024 * 1024) - 1)
        f.write(b"0")

    with pytest.raises(ValueError, match="File too large"):
        await EPUBExtractor("src", "Books", epub_extraction_max_size_mb=1).extract_with_timeout(str(file_path))


@pytest.mark.asyncio
async def test_invalid_epub_falls_back_to_metadata_only(temp_dir):
    file_path = temp_dir / "broken.epub"
    file_path.write_bytes(b"not a zip")

    doc = await EPUBExtractor("src", "Books").extract_with_timeout(str(file_path))

    assert doc.type == "epub"
    assert doc.title == "broken"
    assert "broken.epub" in doc.content
    assert str(file_path.absolute()) in doc.content
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "extraction_error" in doc.metadata


def test_epub_extension_is_registered(temp_dir):
    assert EPUBExtractor.supports_file(str(temp_dir / "book.epub"))
    assert extractor_registry.get_extractor(str(temp_dir / "book.epub"), "src", "Source") is not None
