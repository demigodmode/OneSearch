# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for Pydantic schemas - validation, defaults, edge cases
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.schemas import (
    Document,
    SourceResponse,
    SearchQuery,
    SetupRequest,
)


class TestSourceResponseFromOrm:

    def _make_source(self, **overrides):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        defaults = dict(
            id="src-1",
            root_path="/data/test",
            include_patterns=json.dumps(["**/*.txt"]),
            exclude_patterns=json.dumps(["**/node_modules/**"]),
            scan_schedule="@daily",
            created_at=now,
            updated_at=now,
            last_scan_at=None,
            next_scan_at=None,
        )
        defaults.update(overrides)
        # Mock(name=...) sets the mock's internal name, not an attribute.
        # Use a SimpleNamespace instead to avoid that pitfall.
        from types import SimpleNamespace
        obj = SimpleNamespace(**defaults)
        obj.name = overrides.get("name", "Test")
        return obj

    def test_normal_conversion(self):
        source = self._make_source()
        resp = SourceResponse.from_orm_model(source)

        assert resp.id == "src-1"
        assert resp.include_patterns == ["**/*.txt"]
        assert resp.exclude_patterns == ["**/node_modules/**"]
        assert resp.scan_schedule == "@daily"

    def test_null_patterns(self):
        source = self._make_source(
            include_patterns=None,
            exclude_patterns=None,
        )
        resp = SourceResponse.from_orm_model(source)

        assert resp.include_patterns is None
        assert resp.exclude_patterns is None

    def test_corrupted_json_raises(self):
        source = self._make_source(include_patterns="not json {{{")

        with pytest.raises(json.JSONDecodeError):
            SourceResponse.from_orm_model(source)


class TestDocumentValidation:

    def test_required_fields(self):
        """Document requires all core fields"""
        with pytest.raises(Exception):
            Document()

    def test_defaults(self):
        doc = Document(
            id="src--abc123",
            source_id="src",
            source_name="Source",
            path="/file.txt",
            basename="file.txt",
            extension="txt",
            type="text",
            size_bytes=100,
            modified_at=1700000000,
            indexed_at=1700000000,
            content="hello",
        )
        assert doc.title is None
        assert doc.metadata == {}


class TestSetupRequest:

    def test_boundary_username_min(self):
        """Exactly 3 chars should pass"""
        req = SetupRequest(username="abc", password="12345678")
        assert req.username == "abc"

    def test_boundary_password_min(self):
        """Exactly 8 chars should pass"""
        req = SetupRequest(username="admin", password="abcdefgh")
        assert req.password == "abcdefgh"

    def test_username_too_short(self):
        with pytest.raises(Exception):
            SetupRequest(username="ab", password="12345678")

    def test_password_too_short(self):
        with pytest.raises(Exception):
            SetupRequest(username="admin", password="1234567")


class TestSearchQuery:

    def test_defaults(self):
        q = SearchQuery(q="hello")
        assert q.limit == 20
        assert q.offset == 0

    def test_limit_boundary_low(self):
        q = SearchQuery(q="x", limit=1)
        assert q.limit == 1

    def test_limit_boundary_high(self):
        q = SearchQuery(q="x", limit=100)
        assert q.limit == 100

    def test_limit_too_high(self):
        with pytest.raises(Exception):
            SearchQuery(q="x", limit=101)

    def test_limit_too_low(self):
        with pytest.raises(Exception):
            SearchQuery(q="x", limit=0)

    def test_offset_zero(self):
        q = SearchQuery(q="x", offset=0)
        assert q.offset == 0

    def test_negative_offset_fails(self):
        with pytest.raises(Exception):
            SearchQuery(q="x", offset=-1)
