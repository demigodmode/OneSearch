# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Document extractors package

Import all extractors to ensure they register with the extractor_registry
"""
from .base import BaseExtractor, ExtractorRegistry, extractor_registry
from .text import TextExtractor
from .markdown import MarkdownExtractor
from .pdf import PDFExtractor
from .office import DocxExtractor, XlsxExtractor, PptxExtractor
from .metadata import MetadataOnlyExtractor
from .subtitles import SubtitleExtractor
from .rtf import RTFExtractor
from .epub import EPUBExtractor
from .comic import ComicExtractor
from .images import ImageExtractor
from .media import MediaExtractor

__all__ = [
    "BaseExtractor",
    "ExtractorRegistry",
    "extractor_registry",
    "TextExtractor",
    "MarkdownExtractor",
    "PDFExtractor",
    "DocxExtractor",
    "XlsxExtractor",
    "PptxExtractor",
    "MetadataOnlyExtractor",
    "SubtitleExtractor",
    "RTFExtractor",
    "EPUBExtractor",
    "ComicExtractor",
    "ImageExtractor",
    "MediaExtractor",
]
