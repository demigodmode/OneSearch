# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
EPUB extractor for ebook metadata and spine text.
"""
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from .base import BaseExtractor, extractor_registry
from .metadata import MetadataOnlyExtractor
from ..config import settings
from ..schemas import Document

_CONTAINER_NS = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class _HTMLTextExtractor(HTMLParser):
    """Small HTML-to-text helper for XHTML chapters."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in {"p", "div", "section", "article", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag.lower() in {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return _normalize_text("".join(self.parts))


class EPUBExtractor(BaseExtractor):
    """Extract metadata and readable spine text from EPUB ebooks."""

    SUPPORTED_EXTENSIONS = [".epub"]
    MAX_FILE_SIZE = settings.max_office_file_size_mb * 1024 * 1024
    TIMEOUT = settings.office_extraction_timeout

    def extract(self, file_path: str) -> Document:
        self._check_file_size(file_path)
        try:
            content, metadata = self._extract_epub(file_path)
            doc = self._create_base_document(file_path, content)
            doc.type = "epub"
            doc.title = metadata.get("title") or Path(file_path).stem
            metadata["extraction_failed"] = False
            doc.metadata = metadata
            return doc
        except (BadZipFile, KeyError, ET.ParseError, ValueError, OSError) as e:
            doc = MetadataOnlyExtractor(self.source_id, self.source_name).extract(file_path)
            doc.type = "epub"
            doc.title = Path(file_path).stem
            doc.metadata.update({
                "metadata_only": True,
                "extraction_failed": True,
                "extraction_error": str(e),
            })
            return doc

    def _extract_epub(self, file_path: str) -> tuple[str, dict]:
        with ZipFile(file_path) as zf:
            opf_path = self._get_opf_path(zf)
            opf_root = ET.fromstring(zf.read(opf_path))
            metadata = self._extract_metadata(opf_root)
            chapter_paths = self._spine_chapter_paths(opf_root, opf_path)
            chapter_texts = [self._read_chapter_text(zf, path) for path in chapter_paths]

        metadata["chapter_count"] = len(chapter_paths)
        summary = self._metadata_summary(metadata)
        content = _normalize_text("\n\n".join([summary, *chapter_texts]))
        return content, metadata

    def _get_opf_path(self, zf: ZipFile) -> str:
        root = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = root.find(".//container:rootfile", _CONTAINER_NS)
        if rootfile is None:
            raise ValueError("EPUB container has no rootfile")
        opf_path = rootfile.attrib.get("full-path")
        if not opf_path:
            raise ValueError("EPUB rootfile is missing full-path")
        return opf_path

    def _extract_metadata(self, opf_root: ET.Element) -> dict:
        metadata_el = opf_root.find("opf:metadata", _OPF_NS)
        if metadata_el is None:
            return {}
        fields = {
            "title": "dc:title",
            "creator": "dc:creator",
            "language": "dc:language",
            "publisher": "dc:publisher",
            "date": "dc:date",
            "identifier": "dc:identifier",
        }
        metadata: dict[str, str] = {}
        for key, selector in fields.items():
            el = metadata_el.find(selector, _OPF_NS)
            if el is not None and el.text and el.text.strip():
                metadata[key] = el.text.strip()
        return metadata

    def _spine_chapter_paths(self, opf_root: ET.Element, opf_path: str) -> list[str]:
        readable_media_types = {"application/xhtml+xml", "text/html"}
        manifest_items = {
            item.attrib.get("id"): item.attrib.get("href")
            for item in opf_root.findall("opf:manifest/opf:item", _OPF_NS)
            if item.attrib.get("id")
            and item.attrib.get("href")
            and item.attrib.get("media-type") in readable_media_types
        }
        opf_dir = posixpath.dirname(opf_path)
        chapter_paths: list[str] = []
        for itemref in opf_root.findall("opf:spine/opf:itemref", _OPF_NS):
            href = manifest_items.get(itemref.attrib.get("idref"))
            if href:
                chapter_paths.append(posixpath.normpath(posixpath.join(opf_dir, href)))
        return chapter_paths

    def _read_chapter_text(self, zf: ZipFile, chapter_path: str) -> str:
        data = zf.read(chapter_path).decode("utf-8", errors="replace")
        parser = _HTMLTextExtractor()
        parser.feed(data)
        return parser.text()

    def _metadata_summary(self, metadata: dict) -> str:
        labels = {
            "title": "Title",
            "creator": "Creator",
            "language": "Language",
            "publisher": "Publisher",
            "date": "Date",
            "identifier": "Identifier",
        }
        return "\n".join(
            f"{label}: {metadata[key]}"
            for key, label in labels.items()
            if key in metadata
        )


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank and compact:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False
    return "\n".join(compact).strip()


extractor_registry.register(EPUBExtractor)
