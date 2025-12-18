# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
File system scanner with glob pattern filtering
Walks directory trees and yields files matching include/exclude patterns
"""
import os
from pathlib import Path
from typing import List, Optional, Iterator
import logging

logger = logging.getLogger(__name__)


class FileScanner:
    """
    Scans file system directories with glob pattern filtering

    Supports:
    - Include patterns (whitelist)
    - Exclude patterns (blacklist)
    - Recursive directory traversal
    - Symlink handling
    """

    def __init__(
        self,
        root_path: str,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        follow_symlinks: bool = False
    ):
        """
        Initialize file scanner

        Args:
            root_path: Root directory to scan
            include_patterns: Glob patterns for files to include (e.g., ["**/*.pdf", "**/*.txt"])
            exclude_patterns: Glob patterns for files to exclude (e.g., ["**/node_modules/**", "**/.git/**"])
                             If None, defaults to common exclusions (VCS, dependencies, build dirs)
            follow_symlinks: Whether to follow symbolic links
        """
        self.root_path = Path(root_path).resolve()
        self.include_patterns = include_patterns or ["**/*"]  # Default: all files

        # Default to excluding common directories that shouldn't be indexed
        if exclude_patterns is None:
            self.exclude_patterns = get_default_exclude_patterns()
        else:
            self.exclude_patterns = exclude_patterns

        self.follow_symlinks = follow_symlinks

        # Validate root path
        if not self.root_path.exists():
            raise FileNotFoundError(f"Root path does not exist: {root_path}")
        if not self.root_path.is_dir():
            raise ValueError(f"Root path is not a directory: {root_path}")

    def scan(self) -> Iterator[str]:
        """
        Scan directory and yield matching file paths

        Yields:
            Absolute path to each matching file

        Note:
            Files are yielded as absolute paths (strings)
        """
        # Get all files matching include patterns
        included_files = set()
        for pattern in self.include_patterns:
            try:
                for file_path in self.root_path.glob(pattern):
                    # Only include actual files (not directories)
                    if file_path.is_file():
                        included_files.add(file_path.resolve())
            except Exception as e:
                logger.warning(f"Error processing include pattern '{pattern}': {e}")
                continue

        # Check if file should be excluded based on path matching exclude patterns
        def should_exclude(file_path: Path) -> bool:
            """Check if file path matches any exclude pattern"""
            for pattern in self.exclude_patterns:
                # Check if the file itself matches
                if file_path.match(pattern):
                    return True
                # Check if any parent directory matches the pattern
                # This handles patterns like **/node_modules/** correctly
                try:
                    relative_path = file_path.relative_to(self.root_path)
                    # Check each part of the path
                    if relative_path.match(pattern):
                        return True
                except ValueError:
                    pass
            return False

        # Filter and yield files
        final_files = []
        for file_path in included_files:
            if not should_exclude(file_path):
                # Skip symlinks if not following them
                if not self.follow_symlinks and file_path.is_symlink():
                    logger.debug(f"Skipping symlink: {file_path}")
                    continue
                final_files.append(str(file_path))

        # Sort for consistent ordering (sort strings, not Path objects)
        for file_path in sorted(final_files):
            yield file_path

    def scan_with_stats(self) -> tuple[List[str], dict]:
        """
        Scan directory and return files with statistics

        Returns:
            Tuple of (list of file paths, statistics dict)
        """
        files = list(self.scan())

        stats = {
            "total_files": len(files),
            "root_path": str(self.root_path),
            "include_patterns": self.include_patterns,
            "exclude_patterns": self.exclude_patterns,
        }

        return files, stats

    def count_files(self) -> int:
        """
        Count matching files without loading all paths into memory

        Returns:
            Number of matching files
        """
        count = 0
        for _ in self.scan():
            count += 1
        return count

    def get_file_types(self) -> dict[str, int]:
        """
        Get count of files by extension

        Returns:
            Dictionary mapping extension to count
        """
        extension_counts = {}

        for file_path in self.scan():
            ext = Path(file_path).suffix.lower()
            if not ext:
                ext = "(no extension)"
            extension_counts[ext] = extension_counts.get(ext, 0) + 1

        return extension_counts


def validate_glob_patterns(patterns: List[str]) -> tuple[bool, Optional[str]]:
    """
    Validate glob patterns for common issues

    Args:
        patterns: List of glob patterns to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not patterns:
        return True, None

    for pattern in patterns:
        # Check for empty patterns
        if not pattern or not pattern.strip():
            return False, "Empty pattern found"

        # Check for absolute paths (glob patterns should be relative)
        if pattern.startswith('/') or (len(pattern) > 1 and pattern[1] == ':'):
            return False, f"Pattern should not be absolute path: {pattern}"

        # Warn about patterns without wildcards (inefficient)
        if '*' not in pattern and '?' not in pattern and '[' not in pattern:
            logger.warning(f"Pattern '{pattern}' has no wildcards - may be inefficient")

    return True, None


def get_default_exclude_patterns() -> List[str]:
    """
    Get recommended default exclude patterns for common directories to skip

    Returns:
        List of default exclude patterns
    """
    return [
        # Version control
        "**/.git/**",
        "**/.svn/**",
        "**/.hg/**",

        # Dependencies
        "**/node_modules/**",
        "**/venv/**",
        "**/.venv/**",
        "**/env/**",
        "**/virtualenv/**",
        "**/__pycache__/**",
        "**/vendor/**",

        # Build outputs
        "**/dist/**",
        "**/build/**",
        "**/target/**",
        "**/.next/**",
        "**/.nuxt/**",

        # IDE
        "**/.vscode/**",
        "**/.idea/**",
        "**/.vs/**",

        # OS
        "**/.DS_Store",
        "**/Thumbs.db",
        "**/desktop.ini",

        # Temporary files
        "**/*.tmp",
        "**/*.temp",
        "**/.cache/**",
    ]
