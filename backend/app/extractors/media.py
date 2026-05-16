# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Optional ffprobe-based media metadata extractor.
"""
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from .base import BaseExtractor, extractor_registry
from .metadata import MetadataOnlyExtractor
from ..config import settings
from ..schemas import Document
from ..services.app_settings import default_app_settings

_MEDIA_EXTENSIONS = [".mp4", ".mkv", ".mov", ".avi", ".mp3", ".flac", ".m4a", ".ogg", ".wav"]


class MediaExtractor(BaseExtractor):
    """Extract searchable media metadata with optional ffprobe support."""

    SUPPORTED_EXTENSIONS = _MEDIA_EXTENSIONS
    MAX_FILE_SIZE = settings.max_office_file_size_mb * 1024 * 1024
    TIMEOUT = settings.office_extraction_timeout

    def __init__(
        self,
        source_id: str,
        source_name: str,
        media_metadata_mode: Literal["auto", "off"] | None = None,
        media_probe_max_size_mb: int | None = None,
    ):
        super().__init__(source_id, source_name)
        self.media_metadata_mode = media_metadata_mode
        self.media_probe_max_size_mb = media_probe_max_size_mb

    def set_media_metadata_mode(self, mode: Literal["auto", "off"]) -> None:
        self.media_metadata_mode = mode

    def set_media_probe_max_size_mb(self, max_size_mb: int) -> None:
        self.media_probe_max_size_mb = max_size_mb

    def extract(self, file_path: str) -> Document:
        mode = self._media_metadata_mode()
        if mode == "off":
            return self._metadata_only(file_path, metadata_updates={"media_metadata_mode": "off"})

        try:
            self._check_file_size_limit(file_path, self._media_probe_max_size_bytes())
            ffprobe = shutil.which("ffprobe")
            if ffprobe is None:
                return self._metadata_only(
                    file_path,
                    metadata_updates={
                        "media_metadata_unavailable": True,
                        "extraction_error": "ffprobe executable not found",
                    },
                )

            metadata = self._probe(file_path, ffprobe)
            doc = self._create_base_document(file_path, self._content_summary(Path(file_path).name, metadata))
            doc.type = "media"
            doc.title = str(metadata.get("title") or Path(file_path).stem)
            metadata["metadata_only"] = False
            metadata["extraction_failed"] = False
            doc.metadata = metadata
            return doc
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as e:
            return self._metadata_only(
                file_path,
                failed=True,
                metadata_updates={"extraction_error": str(e)},
            )

    def _media_metadata_mode(self) -> Literal["auto", "off"]:
        if self.media_metadata_mode is None:
            return default_app_settings().media_metadata_mode
        return self.media_metadata_mode

    def _media_probe_max_size_bytes(self) -> int:
        if self.media_probe_max_size_mb is None:
            self.media_probe_max_size_mb = default_app_settings().media_probe_max_size_mb
        return self.media_probe_max_size_mb * 1024 * 1024

    def _metadata_only(
        self,
        file_path: str,
        *,
        failed: bool = False,
        metadata_updates: dict[str, Any] | None = None,
    ) -> Document:
        path = Path(file_path)
        doc = MetadataOnlyExtractor(self.source_id, self.source_name).extract(file_path)
        doc.type = "media"
        doc.title = path.stem
        doc.metadata.update({
            "metadata_only": True,
            "unsupported_extension": False,
            "extraction_failed": failed,
        })
        if metadata_updates:
            doc.metadata.update(metadata_updates)
        return doc

    def _probe(self, file_path: str, ffprobe: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=self.TIMEOUT,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "ffprobe failed")

        payload = json.loads(result.stdout or "{}")
        return _parse_ffprobe_payload(payload)

    def _content_summary(self, basename: str, metadata: dict[str, Any]) -> str:
        labels = {
            "title": "Title",
            "artist": "Artist",
            "album": "Album",
            "date": "Date",
            "format_name": "Format",
            "duration_seconds": "Duration seconds",
            "bit_rate": "Bit rate",
            "video_codec": "Video codec",
            "audio_codec": "Audio codec",
            "frame_rate": "Frame rate",
            "sample_rate": "Sample rate",
            "channels": "Channels",
        }
        lines = [basename]
        for key, label in labels.items():
            if key in metadata:
                lines.append(f"{label}: {metadata[key]}")
        if "width" in metadata and "height" in metadata:
            lines.append(f"Dimensions: {metadata['width']}x{metadata['height']}")
        return "\n".join(lines)


def _parse_ffprobe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    format_info = payload.get("format") or {}
    tags = format_info.get("tags") or {}

    for key in ["format_name", "format_long_name"]:
        if format_info.get(key):
            metadata[key] = format_info[key]

    if format_info.get("duration"):
        metadata["duration_seconds"] = round(float(format_info["duration"]), 3)
    if format_info.get("bit_rate"):
        metadata["bit_rate"] = int(format_info["bit_rate"])

    for source_key, target_key in {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "date": "date",
        "creation_time": "date",
    }.items():
        value = _case_insensitive_get(tags, source_key)
        if value and target_key not in metadata:
            metadata[target_key] = str(value)

    for stream in payload.get("streams") or []:
        stream_type = stream.get("codec_type")
        if stream_type == "video" and "video_codec" not in metadata:
            metadata["video_codec"] = stream.get("codec_name")
            if stream.get("width"):
                metadata["width"] = int(stream["width"])
            if stream.get("height"):
                metadata["height"] = int(stream["height"])
            frame_rate = _format_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
            if frame_rate:
                metadata["frame_rate"] = frame_rate
        elif stream_type == "audio" and "audio_codec" not in metadata:
            metadata["audio_codec"] = stream.get("codec_name")
            if stream.get("channels"):
                metadata["channels"] = int(stream["channels"])
            if stream.get("sample_rate"):
                metadata["sample_rate"] = int(stream["sample_rate"])

    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _case_insensitive_get(values: dict[str, Any], key: str) -> Any:
    for existing_key, value in values.items():
        if existing_key.lower() == key.lower():
            return value
    return None


def _format_frame_rate(value: Any) -> str | None:
    if not value or value == "0/0":
        return None
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_int = int(denominator)
        if denominator_int == 0:
            return None
        fps = int(numerator) / denominator_int
        return f"{fps:.2f}".rstrip("0").rstrip(".")
    return str(value)


extractor_registry.register(MediaExtractor)
