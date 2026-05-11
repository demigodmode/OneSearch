# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
CBZ comic archive metadata extractor.
"""
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from .base import BaseExtractor, extractor_registry
from .metadata import MetadataOnlyExtractor
from ..config import settings
from ..schemas import Document

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}
_COMIC_INFO_FIELDS = {
    "Title": "title",
    "Series": "series",
    "Number": "number",
    "Writer": "writer",
    "Publisher": "publisher",
    "Year": "year",
    "Summary": "summary",
}


class ComicExtractor(BaseExtractor):
    """Index CBZ page listings and ComicInfo metadata."""

    SUPPORTED_EXTENSIONS = [".cbz"]
    MAX_FILE_SIZE = settings.max_office_file_size_mb * 1024 * 1024
    TIMEOUT = settings.office_extraction_timeout

    def extract(self, file_path: str) -> Document:
        self._check_file_size(file_path)
        try:
            content, metadata = self._extract_cbz(file_path)
            doc = self._create_base_document(file_path, content)
            doc.type = "comic"
            doc.title = metadata.get("title") or Path(file_path).stem
            metadata["extraction_failed"] = False
            doc.metadata = metadata
            return doc
        except (BadZipFile, ET.ParseError, OSError, KeyError) as e:
            doc = MetadataOnlyExtractor(self.source_id, self.source_name).extract(file_path)
            doc.type = "comic"
            doc.title = Path(file_path).stem
            doc.metadata.update({
                "metadata_only": True,
                "extraction_failed": True,
                "extraction_error": str(e),
            })
            return doc

    def _extract_cbz(self, file_path: str) -> tuple[str, dict]:
        with ZipFile(file_path) as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            page_files = sorted(
                (
                    name for name in names
                    if Path(name).suffix.lower() in _IMAGE_EXTENSIONS
                ),
                key=_natural_sort_key,
            )
            metadata = self._comic_info_metadata(zf)

        metadata["page_count"] = len(page_files)
        metadata["page_files"] = page_files
        content = self._content_summary(Path(file_path).name, metadata, page_files)
        return content, metadata

    def _comic_info_metadata(self, zf: ZipFile) -> dict:
        comic_info_name = next(
            (name for name in zf.namelist() if name.lower().endswith("comicinfo.xml")),
            None,
        )
        if comic_info_name is None:
            return {}

        root = ET.fromstring(zf.read(comic_info_name))
        metadata: dict[str, str] = {}
        for xml_name, metadata_key in _COMIC_INFO_FIELDS.items():
            value = root.findtext(xml_name)
            if value and value.strip():
                metadata[metadata_key] = value.strip()
        return metadata

    def _content_summary(self, basename: str, metadata: dict, page_files: list[str]) -> str:
        labels = {
            "title": "Title",
            "series": "Series",
            "number": "Number",
            "writer": "Writer",
            "publisher": "Publisher",
            "year": "Year",
            "summary": "Summary",
        }
        lines = [basename]
        for key, label in labels.items():
            if key in metadata:
                lines.append(f"{label}: {metadata[key]}")
        lines.append(f"Page count: {len(page_files)}")
        lines.extend(page_files)
        return "\n".join(lines)


def _natural_sort_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


extractor_registry.register(ComicExtractor)
