# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
CBZ comic archive metadata extractor.
"""
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from ..config import settings
from ..schemas import Document
from .base import BaseExtractor, extractor_registry
from .metadata import MetadataOnlyExtractor

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
_MAX_COMIC_INFO_BYTES = 1 * 1024 * 1024
_MAX_CBZ_PAGE_FILES = 10_000


class ComicExtractor(BaseExtractor):
    """Index CBZ page listings and ComicInfo metadata."""

    SUPPORTED_EXTENSIONS = [".cbz"]
    MAX_FILE_SIZE = settings.max_office_file_size_mb * 1024 * 1024
    TIMEOUT = settings.office_extraction_timeout

    def __init__(self, source_id: str, source_name: str, comic_extraction_max_size_mb: int | None = None):
        super().__init__(source_id, source_name)
        self.comic_extraction_max_size_mb = comic_extraction_max_size_mb

    def set_comic_extraction_max_size_mb(self, max_size_mb: int) -> None:
        self.comic_extraction_max_size_mb = max_size_mb

    def extract(self, file_path: str) -> Document:
        self._check_file_size_limit(file_path, self._comic_extraction_max_size_bytes())
        try:
            content, metadata = self._extract_cbz(file_path)
            doc = self._create_base_document(file_path, content)
            doc.type = "comic"
            doc.title = metadata.get("title") or Path(file_path).stem
            metadata["extraction_failed"] = False
            doc.metadata = metadata
            return doc
        except (BadZipFile, ET.ParseError, OSError, KeyError, ValueError) as e:
            doc = MetadataOnlyExtractor(self.source_id, self.source_name).extract(file_path)
            doc.type = "comic"
            doc.title = Path(file_path).stem
            doc.metadata.update({
                "metadata_only": True,
                "extraction_failed": True,
                "extraction_error": str(e),
            })
            return doc

    def _comic_extraction_max_size_bytes(self) -> int:
        from ..services.app_settings import default_app_settings
        if self.comic_extraction_max_size_mb is None:
            self.comic_extraction_max_size_mb = default_app_settings().comic_extraction_max_size_mb
        return self.comic_extraction_max_size_mb * 1024 * 1024

    def _extract_cbz(self, file_path: str) -> tuple[str, dict]:
        with ZipFile(file_path) as zf:
            page_files: list[str] = []
            for info in zf.infolist():
                if info.is_dir() or Path(info.filename).suffix.lower() not in _IMAGE_EXTENSIONS:
                    continue
                page_files.append(info.filename)
                if len(page_files) > _MAX_CBZ_PAGE_FILES:
                    raise ValueError("CBZ archive has too many page files")
            page_files.sort(key=_natural_sort_key)
            metadata = self._comic_info_metadata(zf)

        metadata["page_count"] = len(page_files)
        metadata["page_files"] = page_files
        content = self._content_summary(Path(file_path).name, metadata, page_files)
        return content, metadata

    def _comic_info_metadata(self, zf: ZipFile) -> dict:
        comic_info_name = next(
            (info.filename for info in zf.infolist() if not info.is_dir() and info.filename.lower().endswith("comicinfo.xml")),
            None,
        )
        if comic_info_name is None:
            return {}

        root = ET.fromstring(_read_zip_entry(zf, comic_info_name, _MAX_COMIC_INFO_BYTES))
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


def _read_zip_entry(zf: ZipFile, name: str, max_bytes: int) -> bytes:
    entry_size = zf.getinfo(name).file_size
    if entry_size > max_bytes:
        raise ValueError(f"CBZ archive entry too large: {name}")
    return zf.read(name)


def _natural_sort_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


extractor_registry.register(ComicExtractor)
