# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""--json output has to stay parseable when stdout isn't a terminal."""

import json

from click.testing import CliRunner

from onesearch.context import Context
from onesearch.main import cli

LONG_TEXT = "lorem ipsum dolor sit amet " * 10


class FakeAPI:
    def search(self, **kwargs):
        return {
            "results": [{"path": "/docs/notes.txt", "snippet": LONG_TEXT}],
            "total": 1,
            "limit": 20,
            "offset": 0,
            "processing_time_ms": 3,
        }

    def status(self):
        return {"sources": [{"source_id": "s1", "source_name": LONG_TEXT, "total_files": 1}]}

    def source_status(self, source_id):
        return {"source_id": source_id, "source_name": LONG_TEXT, "total_files": 1, "failed_files": []}

    def health(self, allow_degraded=False):
        return {"status": "ok", "version": "0.0.0", "message": LONG_TEXT}


def _invoke(monkeypatch, args):
    monkeypatch.setattr(Context, "get_api", lambda self: FakeAPI())
    runner = CliRunner()
    return runner.invoke(cli, ["--url", "http://testserver", *args], obj=Context())


def test_search_json_is_valid_with_long_strings(monkeypatch):
    result = _invoke(monkeypatch, ["search", "lorem", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["results"][0]["snippet"] == LONG_TEXT


def test_status_json_is_valid_with_long_strings(monkeypatch):
    result = _invoke(monkeypatch, ["status", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sources"][0]["source_name"] == LONG_TEXT


def test_source_status_json_is_valid_with_long_strings(monkeypatch):
    result = _invoke(monkeypatch, ["status", "s1", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["source_name"] == LONG_TEXT


def test_health_json_is_valid_with_long_strings(monkeypatch):
    result = _invoke(monkeypatch, ["health", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["message"] == LONG_TEXT
