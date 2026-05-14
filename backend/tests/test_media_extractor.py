# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for optional ffprobe-based media metadata extraction.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.extractors import MediaExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_media_file(path: Path) -> None:
    path.write_bytes(b"fake media bytes")


@pytest.mark.asyncio
async def test_media_metadata_mode_off_indexes_metadata_only(temp_dir, monkeypatch):
    file_path = temp_dir / "song.mp3"
    write_media_file(file_path)
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.extractors.media.subprocess.run", fake_run)

    doc = await MediaExtractor("src", "Media", media_metadata_mode="off").extract_with_timeout(str(file_path))

    assert called is False
    assert doc.type == "media"
    assert doc.title == "song"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is False
    assert doc.metadata["media_metadata_mode"] == "off"
    assert "song.mp3" in doc.content


@pytest.mark.asyncio
async def test_ffprobe_unavailable_indexes_metadata_only(temp_dir, monkeypatch):
    file_path = temp_dir / "movie.mp4"
    write_media_file(file_path)
    monkeypatch.setattr("app.extractors.media.shutil.which", lambda name: None)

    doc = await MediaExtractor("src", "Media", media_metadata_mode="auto").extract_with_timeout(str(file_path))

    assert doc.type == "media"
    assert doc.title == "movie"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is False
    assert doc.metadata["media_metadata_unavailable"] is True
    assert "ffprobe" in doc.metadata["extraction_error"].lower()


@pytest.mark.asyncio
async def test_ffprobe_json_output_is_indexed_as_searchable_metadata(temp_dir, monkeypatch):
    file_path = temp_dir / "clip.mkv"
    write_media_file(file_path)
    monkeypatch.setattr("app.extractors.media.shutil.which", lambda name: "ffprobe")

    ffprobe_output = {
        "format": {
            "format_name": "matroska,webm",
            "duration": "12.345000",
            "bit_rate": "1234567",
            "tags": {
                "title": "Demo Clip",
                "artist": "Example Artist",
                "album": "Example Album",
                "date": "2024",
            },
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
            },
        ],
    }

    class Result:
        returncode = 0
        stdout = json.dumps(ffprobe_output)
        stderr = ""

    def fake_run(args, **kwargs):
        assert args[0] == "ffprobe"
        assert str(file_path) in args
        return Result()

    monkeypatch.setattr("app.extractors.media.subprocess.run", fake_run)

    doc = await MediaExtractor("src", "Media", media_metadata_mode="auto").extract_with_timeout(str(file_path))

    assert doc.type == "media"
    assert doc.title == "Demo Clip"
    assert doc.metadata["metadata_only"] is False
    assert doc.metadata["extraction_failed"] is False
    assert doc.metadata["format_name"] == "matroska,webm"
    assert doc.metadata["duration_seconds"] == 12.345
    assert doc.metadata["bit_rate"] == 1234567
    assert doc.metadata["title"] == "Demo Clip"
    assert doc.metadata["artist"] == "Example Artist"
    assert doc.metadata["album"] == "Example Album"
    assert doc.metadata["date"] == "2024"
    assert doc.metadata["video_codec"] == "h264"
    assert doc.metadata["width"] == 1920
    assert doc.metadata["height"] == 1080
    assert doc.metadata["frame_rate"] == "29.97"
    assert doc.metadata["audio_codec"] == "aac"
    assert doc.metadata["channels"] == 2
    assert doc.metadata["sample_rate"] == 48000
    assert "Demo Clip" in doc.content
    assert "Example Artist" in doc.content
    assert "h264" in doc.content
    assert "1920x1080" in doc.content
    assert "aac" in doc.content


@pytest.mark.asyncio
async def test_ffprobe_failure_indexes_metadata_only_with_error(temp_dir, monkeypatch):
    file_path = temp_dir / "broken.wav"
    write_media_file(file_path)
    monkeypatch.setattr("app.extractors.media.shutil.which", lambda name: "ffprobe")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "invalid data"

    monkeypatch.setattr("app.extractors.media.subprocess.run", lambda *args, **kwargs: Result())

    doc = await MediaExtractor("src", "Media", media_metadata_mode="auto").extract_with_timeout(str(file_path))

    assert doc.type == "media"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "invalid data" in doc.metadata["extraction_error"]


def test_media_extensions_are_registered(temp_dir):
    for name in ["video.mp4", "video.mkv", "video.mov", "video.avi", "song.mp3", "song.flac", "song.m4a", "song.ogg", "song.wav"]:
        assert MediaExtractor.supports_file(str(temp_dir / name)), name
        assert extractor_registry.get_extractor(str(temp_dir / name), "src", "Source") is not None
