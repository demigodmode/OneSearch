# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Services package

Exports all service classes and instances
"""
from .search import MeilisearchService, SearchService, meili_service
from .scanner import FileScanner, validate_glob_patterns, get_default_exclude_patterns
from .indexer import IndexingService, IndexingStats

__all__ = [
    "MeilisearchService",
    "SearchService",
    "meili_service",
    "FileScanner",
    "validate_glob_patterns",
    "get_default_exclude_patterns",
    "IndexingService",
    "IndexingStats",
]
