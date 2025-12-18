# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for file scanner
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.scanner import (
    FileScanner,
    validate_glob_patterns,
    get_default_exclude_patterns,
)


@pytest.fixture
def test_directory():
    """Create test directory with sample files"""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create directory structure
        (tmp_path / "docs").mkdir()
        (tmp_path / "code").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / ".git").mkdir()

        # Create files
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "docs" / "guide.md").write_text("# Guide")
        (tmp_path / "docs" / "api.pdf").touch()
        (tmp_path / "code" / "main.py").write_text("print('hello')")
        (tmp_path / "code" / "test.txt").write_text("test")
        (tmp_path / "node_modules" / "package.json").write_text("{}")
        (tmp_path / ".git" / "config").write_text("")

        yield tmp_path


class TestFileScanner:
    """Tests for FileScanner"""

    def test_scan_all_files(self, test_directory):
        """Test scanning all files"""
        # Explicitly disable default excludes for this test
        scanner = FileScanner(str(test_directory), exclude_patterns=[])
        files = list(scanner.scan())

        # Should find all files including those in subdirectories
        assert len(files) >= 5
        assert any("README.md" in f for f in files)
        assert any("main.py" in f for f in files)

    def test_include_pattern(self, test_directory):
        """Test include pattern filtering"""
        scanner = FileScanner(
            str(test_directory),
            include_patterns=["**/*.md"],
            exclude_patterns=[]  # Disable default excludes
        )
        files = list(scanner.scan())

        # Should only find .md files
        assert all(f.endswith(".md") for f in files)
        assert len(files) == 2  # README.md and docs/guide.md

    def test_multiple_include_patterns(self, test_directory):
        """Test multiple include patterns"""
        scanner = FileScanner(
            str(test_directory),
            include_patterns=["**/*.md", "**/*.py"],
            exclude_patterns=[]  # Disable default excludes
        )
        files = list(scanner.scan())

        # Should find both .md and .py files
        assert any(f.endswith(".md") for f in files)
        assert any(f.endswith(".py") for f in files)
        assert len(files) == 3  # 2 .md + 1 .py

    def test_exclude_pattern(self, test_directory):
        """Test exclude pattern filtering"""
        scanner = FileScanner(
            str(test_directory),
            include_patterns=["**/*"],
            exclude_patterns=["**/node_modules/**", "**/.git/**"]
        )
        files = list(scanner.scan())

        # Should exclude node_modules and .git
        assert not any("node_modules" in f for f in files)
        assert not any(".git" in f for f in files)

    def test_scan_with_stats(self, test_directory):
        """Test scan_with_stats method"""
        scanner = FileScanner(
            str(test_directory),
            include_patterns=["**/*.md"],
            exclude_patterns=[]  # Disable default excludes
        )
        files, stats = scanner.scan_with_stats()

        assert stats["total_files"] == len(files)
        assert stats["root_path"] == str(test_directory)
        assert stats["include_patterns"] == ["**/*.md"]

    def test_count_files(self, test_directory):
        """Test count_files method"""
        scanner = FileScanner(
            str(test_directory),
            include_patterns=["**/*.md"],
            exclude_patterns=[]  # Disable default excludes
        )
        count = scanner.count_files()

        assert count == 2

    def test_get_file_types(self, test_directory):
        """Test get_file_types method"""
        scanner = FileScanner(str(test_directory), exclude_patterns=[])
        file_types = scanner.get_file_types()

        assert ".md" in file_types
        assert ".py" in file_types
        assert ".txt" in file_types
        assert file_types[".md"] == 2

    def test_invalid_root_path(self):
        """Test scanner with invalid root path"""
        with pytest.raises(FileNotFoundError):
            FileScanner("/nonexistent/path")

    def test_sorted_output(self, test_directory):
        """Test that files are returned in sorted order"""
        scanner = FileScanner(str(test_directory), exclude_patterns=[])
        files = list(scanner.scan())

        # Files should be sorted
        assert files == sorted(files)

    def test_empty_directory(self):
        """Test scanning empty directory"""
        with TemporaryDirectory() as tmp:
            scanner = FileScanner(tmp, exclude_patterns=[])
            files = list(scanner.scan())

            assert len(files) == 0

    def test_default_exclude_patterns(self, test_directory):
        """Test that default exclude patterns work correctly"""
        # Scanner with defaults should exclude .git and node_modules
        scanner = FileScanner(str(test_directory))
        files = list(scanner.scan())

        # Should NOT find files in excluded directories
        assert not any(".git" in f for f in files)
        assert not any("node_modules" in f for f in files)


class TestValidateGlobPatterns:
    """Tests for validate_glob_patterns"""

    def test_valid_patterns(self):
        """Test validation of valid patterns"""
        patterns = ["**/*.txt", "**/*.md", "docs/**"]
        is_valid, error = validate_glob_patterns(patterns)

        assert is_valid is True
        assert error is None

    def test_empty_pattern(self):
        """Test validation catches empty patterns"""
        patterns = ["**/*.txt", ""]
        is_valid, error = validate_glob_patterns(patterns)

        assert is_valid is False
        assert "Empty pattern" in error

    def test_absolute_path_pattern(self):
        """Test validation catches absolute paths"""
        patterns = ["/absolute/path/**"]
        is_valid, error = validate_glob_patterns(patterns)

        assert is_valid is False
        assert "absolute path" in error

    def test_empty_list(self):
        """Test validation of empty pattern list"""
        is_valid, error = validate_glob_patterns([])

        assert is_valid is True
        assert error is None


class TestGetDefaultExcludePatterns:
    """Tests for get_default_exclude_patterns"""

    def test_returns_patterns(self):
        """Test that default patterns are returned"""
        patterns = get_default_exclude_patterns()

        assert len(patterns) > 0
        assert "**/.git/**" in patterns
        assert "**/node_modules/**" in patterns
        assert "**/__pycache__/**" in patterns
