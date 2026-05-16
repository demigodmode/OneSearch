# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for RTF extraction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.extractors import RTFExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.mark.asyncio
async def test_extract_rtf_plain_text(temp_dir):
    file_path = temp_dir / "notes.rtf"
    file_path.write_text(
        r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Arial;}}\f0\fs24 Hello \b bold\b0 world\par Second line}",
        encoding="utf-8",
    )

    doc = await RTFExtractor("src", "Documents").extract_with_timeout(str(file_path))

    assert doc.type == "rtf"
    assert doc.title == "notes"
    assert doc.content == "Hello bold world\nSecond line"
    assert "\\b" not in doc.content
    assert doc.metadata["extraction_failed"] is False


@pytest.mark.asyncio
async def test_extract_rtf_decodes_hex_escapes(temp_dir):
    file_path = temp_dir / "latin.rtf"
    file_path.write_text(r"{\rtf1\ansi Caf\'e9}", encoding="utf-8")

    doc = await RTFExtractor("src", "Documents").extract_with_timeout(str(file_path))

    assert doc.content == "Café"


@pytest.mark.asyncio
async def test_extract_rtf_decodes_unicode_escapes(temp_dir):
    file_path = temp_dir / "unicode.rtf"
    file_path.write_text(r"{\rtf1\ansi Unicode \u8212? dash}", encoding="utf-8")

    doc = await RTFExtractor("src", "Documents").extract_with_timeout(str(file_path))

    assert doc.content == "Unicode — dash"


@pytest.mark.asyncio
async def test_extract_rtf_ignores_metadata_groups(temp_dir):
    file_path = temp_dir / "metadata.rtf"
    file_path.write_text(
        r"{\rtf1\ansi{\info{\title Hidden Title}{\author Jane}}Visible text}",
        encoding="utf-8",
    )

    doc = await RTFExtractor("src", "Documents").extract_with_timeout(str(file_path))

    assert doc.content == "Visible text"
    assert "Hidden Title" not in doc.content
    assert "Jane" not in doc.content


def test_rtf_extension_is_registered(temp_dir):
    assert RTFExtractor.supports_file(str(temp_dir / "document.rtf"))
    assert extractor_registry.get_extractor(str(temp_dir / "document.rtf"), "src", "Source") is not None
