# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Subtitle extractor for SRT, WebVTT, and ASS/SSA subtitle files.
"""
import re
from pathlib import Path

import chardet

from .base import BaseExtractor, extractor_registry
from ..config import settings
from ..schemas import Document


_TIMESTAMP_LINE = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s+-->\s+\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")
_VTT_TAG = re.compile(r"</?[^>]+>")
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")


class SubtitleExtractor(BaseExtractor):
    """Extract readable transcript text from subtitle files."""

    SUPPORTED_EXTENSIONS = [".srt", ".vtt", ".ass"]
    MAX_FILE_SIZE = settings.max_text_file_size_mb * 1024 * 1024
    TIMEOUT = settings.text_extraction_timeout

    def extract(self, file_path: str) -> Document:
        self._check_file_size(file_path)
        path = Path(file_path)
        subtitle_format = path.suffix.lower().lstrip(".")
        content = self._read_text(file_path)

        if subtitle_format == "ass":
            transcript_lines, cue_count = self._parse_ass(content)
        elif subtitle_format == "vtt":
            transcript_lines, cue_count = self._parse_vtt(content)
        else:
            transcript_lines, cue_count = self._parse_srt(content)

        transcript = "\n".join(transcript_lines)
        doc = self._create_base_document(file_path, transcript)
        doc.type = "subtitle"
        doc.title = path.stem
        doc.metadata = {
            "subtitle_format": subtitle_format,
            "cue_count": cue_count,
            "extraction_failed": False,
        }
        return doc

    def _read_text(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "rb") as f:
                raw = f.read()
            detected = chardet.detect(raw).get("encoding") or "utf-8"
            return raw.decode(detected, errors="replace")

    def _parse_srt(self, content: str) -> tuple[list[str], int]:
        lines: list[str] = []
        cue_count = 0
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.isdigit():
                continue
            if _TIMESTAMP_LINE.match(line):
                cue_count += 1
                continue
            lines.append(self._clean_text(line))
        return [line for line in lines if line], cue_count

    def _parse_vtt(self, content: str) -> tuple[list[str], int]:
        lines: list[str] = []
        cue_count = 0
        skip_note = False
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                skip_note = False
                continue
            if line == "WEBVTT" or line.startswith("STYLE") or line.startswith("REGION"):
                continue
            if line.startswith("NOTE"):
                skip_note = True
                continue
            if skip_note:
                continue
            if "-->" in line:
                cue_count += 1
                continue
            if re.match(r"^[A-Za-z0-9_-]+$", line):
                continue
            lines.append(self._clean_text(line))
        return [line for line in lines if line], cue_count

    def _parse_ass(self, content: str) -> tuple[list[str], int]:
        lines: list[str] = []
        cue_count = 0
        for raw_line in content.splitlines():
            if not raw_line.startswith("Dialogue:"):
                continue
            cue_count += 1
            dialogue = raw_line[len("Dialogue:"):].strip()
            parts = dialogue.split(",", 9)
            text = parts[9] if len(parts) == 10 else dialogue
            text = text.replace("\\N", "\n").replace("\\n", "\n")
            text = _ASS_OVERRIDE.sub("", text)
            for line in text.splitlines():
                cleaned = self._clean_text(line)
                if cleaned:
                    lines.append(cleaned)
        return lines, cue_count

    def _clean_text(self, text: str) -> str:
        text = _VTT_TAG.sub("", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return text.strip()


extractor_registry.register(SubtitleExtractor)
