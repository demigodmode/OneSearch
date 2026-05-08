# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for subtitle extraction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.extractors import SubtitleExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.mark.asyncio
async def test_extract_srt_transcript(temp_dir):
    file_path = temp_dir / "movie.srt"
    file_path.write_text(
        """1
00:00:01,000 --> 00:00:03,000
Hello there.

2
00:00:04,500 --> 00:00:06,000
General Kenobi!
""",
        encoding="utf-8",
    )

    doc = await SubtitleExtractor("src", "Movies").extract_with_timeout(str(file_path))

    assert doc.type == "subtitle"
    assert doc.title == "movie"
    assert doc.content == "Hello there.\nGeneral Kenobi!"
    assert "00:00" not in doc.content
    assert doc.metadata["subtitle_format"] == "srt"
    assert doc.metadata["cue_count"] == 2
    assert doc.metadata["extraction_failed"] is False


@pytest.mark.asyncio
async def test_extract_vtt_transcript(temp_dir):
    file_path = temp_dir / "clip.vtt"
    file_path.write_text(
        """WEBVTT

NOTE intro comment

00:00:01.000 --> 00:00:02.000
<v Speaker>Welcome home.</v>

00:00:03.000 --> 00:00:04.000 align:start position:0%
Second line
""",
        encoding="utf-8",
    )

    doc = await SubtitleExtractor("src", "Movies").extract_with_timeout(str(file_path))

    assert doc.content == "Welcome home.\nSecond line"
    assert "WEBVTT" not in doc.content
    assert "NOTE" not in doc.content
    assert doc.metadata["subtitle_format"] == "vtt"
    assert doc.metadata["cue_count"] == 2


@pytest.mark.asyncio
async def test_extract_ass_dialogue_text(temp_dir):
    file_path = temp_dir / "episode.ass"
    file_path.write_text(
        """[Script Info]
Title: Test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Styled line{\\i0}
Dialogue: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,Another\\Nline
""",
        encoding="utf-8",
    )

    doc = await SubtitleExtractor("src", "Shows").extract_with_timeout(str(file_path))

    assert doc.content == "Styled line\nAnother\nline"
    assert "Dialogue:" not in doc.content
    assert "{\\i1}" not in doc.content
    assert doc.metadata["subtitle_format"] == "ass"
    assert doc.metadata["cue_count"] == 2


def test_subtitle_extensions_are_registered(temp_dir):
    assert SubtitleExtractor.supports_file(str(temp_dir / "movie.srt"))
    assert SubtitleExtractor.supports_file(str(temp_dir / "movie.vtt"))
    assert SubtitleExtractor.supports_file(str(temp_dir / "movie.ass"))
    assert extractor_registry.get_extractor(str(temp_dir / "movie.srt"), "src", "Source") is not None
