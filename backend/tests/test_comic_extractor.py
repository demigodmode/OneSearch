# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for CBZ comic metadata extraction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import app.extractors.comic as comic_module
from app.extractors import ComicExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_cbz(path: Path, *, include_comic_info: bool = True) -> None:
    comic_info = """<?xml version="1.0" encoding="UTF-8"?>
<ComicInfo>
  <Title>Issue One</Title>
  <Series>Example Series</Series>
  <Number>1</Number>
  <Writer>Jane Writer</Writer>
  <Publisher>Small Comics</Publisher>
  <Year>2024</Year>
  <Summary>A test comic summary.</Summary>
</ComicInfo>
"""
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("pages/001-cover.jpg", b"fake jpg")
        zf.writestr("pages/002-page.png", b"fake png")
        zf.writestr("notes/readme.txt", "not a page")
        if include_comic_info:
            zf.writestr("ComicInfo.xml", comic_info)


@pytest.mark.asyncio
async def test_extract_cbz_page_listing_and_comic_info(temp_dir):
    file_path = temp_dir / "example-series-001.cbz"
    write_cbz(file_path)

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.type == "comic"
    assert doc.title == "Issue One"
    assert "Issue One" in doc.content
    assert "Example Series" in doc.content
    assert "Jane Writer" in doc.content
    assert "001-cover.jpg" in doc.content
    assert "002-page.png" in doc.content
    assert "readme.txt" not in doc.content
    assert doc.metadata["title"] == "Issue One"
    assert doc.metadata["series"] == "Example Series"
    assert doc.metadata["number"] == "1"
    assert doc.metadata["writer"] == "Jane Writer"
    assert doc.metadata["publisher"] == "Small Comics"
    assert doc.metadata["year"] == "2024"
    assert doc.metadata["page_count"] == 2
    assert doc.metadata["page_files"] == ["pages/001-cover.jpg", "pages/002-page.png"]
    assert doc.metadata["extraction_failed"] is False


@pytest.mark.asyncio
async def test_extract_cbz_without_comic_info_uses_filename_title(temp_dir):
    file_path = temp_dir / "standalone-comic.cbz"
    write_cbz(file_path, include_comic_info=False)

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.type == "comic"
    assert doc.title == "standalone-comic"
    assert "standalone-comic.cbz" in doc.content
    assert "pages/001-cover.jpg" in doc.content
    assert doc.metadata["page_count"] == 2
    assert "title" not in doc.metadata


@pytest.mark.asyncio
async def test_cbz_comic_info_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(comic_module, "_MAX_COMIC_INFO_BYTES", 64, raising=False)
    file_path = temp_dir / "oversized-comic-info.cbz"
    with ZipFile(file_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("001.jpg", b"fake jpg")
        zf.writestr(
            "ComicInfo.xml",
            "<ComicInfo><Title>Huge Metadata</Title><Summary>" + ("A" * 1024) + "</Summary></ComicInfo>",
        )

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.type == "comic"
    assert doc.title == "oversized-comic-info"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "CBZ archive" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_cbz_page_count_limit_falls_back_to_metadata_only(temp_dir, monkeypatch):
    monkeypatch.setattr(comic_module, "_MAX_CBZ_PAGE_FILES", 2, raising=False)

    def fail_if_sorted(value):
        raise AssertionError(f"over-limit page list should not be sorted: {value}")

    monkeypatch.setattr(comic_module, "_natural_sort_key", fail_if_sorted)
    file_path = temp_dir / "too-many-pages.cbz"
    with ZipFile(file_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("001.jpg", b"fake jpg")
        zf.writestr("002.jpg", b"fake jpg")
        zf.writestr("003.jpg", b"fake jpg")

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.type == "comic"
    assert doc.title == "too-many-pages"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "CBZ archive" in doc.metadata["extraction_error"]


@pytest.mark.asyncio
async def test_cbz_page_files_use_natural_sort(temp_dir):
    file_path = temp_dir / "natural-sort.cbz"
    with ZipFile(file_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("10.jpg", b"fake jpg")
        zf.writestr("2.jpg", b"fake jpg")
        zf.writestr("1.jpg", b"fake jpg")

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.metadata["page_files"] == ["1.jpg", "2.jpg", "10.jpg"]
    assert doc.content.index("1.jpg") < doc.content.index("2.jpg") < doc.content.index("10.jpg")


@pytest.mark.asyncio
async def test_cbz_uses_comic_specific_size_limit(temp_dir):
    file_path = temp_dir / "large.cbz"
    with file_path.open("wb") as f:
        f.seek((2 * 1024 * 1024) - 1)
        f.write(b"0")

    with pytest.raises(ValueError, match="File too large"):
        await ComicExtractor("src", "Comics", comic_extraction_max_size_mb=1).extract_with_timeout(str(file_path))


@pytest.mark.asyncio
async def test_invalid_cbz_falls_back_to_metadata_only(temp_dir):
    file_path = temp_dir / "broken.cbz"
    file_path.write_bytes(b"not a zip")

    doc = await ComicExtractor("src", "Comics").extract_with_timeout(str(file_path))

    assert doc.type == "comic"
    assert doc.title == "broken"
    assert "broken.cbz" in doc.content
    assert str(file_path.absolute()) in doc.content
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "extraction_error" in doc.metadata


def test_cbz_extension_is_registered(temp_dir):
    assert ComicExtractor.supports_file(str(temp_dir / "comic.cbz"))
    assert extractor_registry.get_extractor(str(temp_dir / "comic.cbz"), "src", "Source") is not None
