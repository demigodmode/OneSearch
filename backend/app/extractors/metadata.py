# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Metadata-only document creation for files without a content extractor.
"""
from pathlib import Path

from .base import BaseExtractor
from ..schemas import Document


class MetadataOnlyExtractor(BaseExtractor):
    """Create searchable filename/path metadata for unsupported files."""

    SUPPORTED_EXTENSIONS: list[str] = []

    def extract(self, file_path: str) -> Document:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")
        metadata = self._get_file_metadata(file_path)
        absolute_path = str(path.absolute())
        content = "\n".join([
            metadata["basename"],
            absolute_path,
            f"Source: {self.source_name}",
            f"Extension: {metadata['extension'] or 'none'}",
            f"Size bytes: {metadata['size_bytes']}",
            f"Modified at: {metadata['modified_at']}",
        ])

        doc = self._create_base_document(file_path, content)
        doc.type = "file"
        doc.title = path.stem or path.name
        doc.metadata = {
            "metadata_only": True,
            "unsupported_extension": True,
            "extraction_failed": False,
        }
        return doc
