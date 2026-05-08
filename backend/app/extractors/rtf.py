# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
RTF extractor with a small bounded text stripper.
"""
import re
from pathlib import Path

from .base import BaseExtractor, extractor_registry
from ..config import settings
from ..schemas import Document


_DESTINATIONS_TO_SKIP = {
    "fonttbl", "colortbl", "datastore", "themedata", "stylesheet", "info",
    "pict", "object", "generator", "comment", "revtbl", "xmlnstbl",
}


class RTFExtractor(BaseExtractor):
    """Extract readable text from Rich Text Format files."""

    SUPPORTED_EXTENSIONS = [".rtf"]
    MAX_FILE_SIZE = settings.max_text_file_size_mb * 1024 * 1024
    TIMEOUT = settings.text_extraction_timeout

    def extract(self, file_path: str) -> Document:
        self._check_file_size(file_path)
        path = Path(file_path)
        raw = Path(file_path).read_text(encoding="latin-1")
        content = self._strip_rtf(raw)

        doc = self._create_base_document(file_path, content)
        doc.type = "rtf"
        doc.title = path.stem
        doc.metadata = {"extraction_failed": False}
        return doc

    def _strip_rtf(self, raw: str) -> str:
        output: list[str] = []
        stack: list[bool] = []
        skip_depth = 0
        i = 0

        while i < len(raw):
            char = raw[i]

            if char == "{":
                stack.append(skip_depth > 0)
                if self._group_should_skip(raw, i + 1):
                    skip_depth += 1
                i += 1
                continue

            if char == "}":
                if stack:
                    was_skipping = stack.pop()
                    if skip_depth > 0 and not was_skipping:
                        skip_depth -= 1
                i += 1
                continue

            if skip_depth > 0:
                i = self._skip_token(raw, i)
                continue

            if char == "\\":
                text, new_i = self._handle_control(raw, i)
                output.append(text)
                i = new_i
                continue

            output.append(char)
            i += 1

        return self._normalize_text("".join(output))

    def _group_should_skip(self, raw: str, start: int) -> bool:
        if start < len(raw) and raw[start] == "*":
            return True
        if start < len(raw) and raw[start] == "\\":
            match = re.match(r"\\([a-zA-Z]+)", raw[start:])
            if match:
                return match.group(1) in _DESTINATIONS_TO_SKIP
        return False

    def _skip_token(self, raw: str, i: int) -> int:
        if raw[i] != "\\":
            return i + 1
        if i + 1 < len(raw) and raw[i + 1] == "'":
            return min(i + 4, len(raw))
        match = re.match(r"\\[a-zA-Z]+-?\d* ?", raw[i:])
        if match:
            return i + len(match.group(0))
        return min(i + 2, len(raw))

    def _handle_control(self, raw: str, i: int) -> tuple[str, int]:
        if i + 1 >= len(raw):
            return "", i + 1

        next_char = raw[i + 1]
        if next_char in "{}\\":
            return next_char, i + 2
        if next_char == "'" and i + 3 < len(raw):
            hex_value = raw[i + 2:i + 4]
            try:
                return bytes.fromhex(hex_value).decode("latin-1"), i + 4
            except ValueError:
                return "", i + 4

        match = re.match(r"\\([a-zA-Z]+)(-?\d*)( ?)", raw[i:])
        if not match:
            return "", i + 2

        word = match.group(1)
        arg = match.group(2)
        replacement = {
            "par": "\n",
            "line": "\n",
            "tab": "\t",
            "emdash": "—",
            "endash": "–",
            "bullet": "•",
        }.get(word, "")
        new_i = i + len(match.group(0))
        if word == "u" and arg:
            codepoint = int(arg)
            if codepoint < 0:
                codepoint += 65536
            replacement = chr(codepoint)
            if new_i < len(raw) and raw[new_i] not in "{}\\\n\r":
                new_i += 1
        elif replacement == "" and match.group(3) == " ":
            replacement = " "
        return replacement, new_i

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\r", "")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        lines = [line for line in lines if line]
        return "\n".join(lines)


extractor_registry.register(RTFExtractor)
