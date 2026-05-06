from click.testing import CliRunner

from onesearch.context import Context
from onesearch.main import cli


def test_api_reindex_source_can_request_full_rebuild():
    from onesearch.api import OneSearchAPI

    calls = []
    api = OneSearchAPI(base_url="http://localhost:8000", token="secret")

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return {"stats": {}}

    api._request = fake_request

    api.reindex_source("docs", full=True)

    assert calls == [("POST", "/api/sources/docs/reindex?full=true", {})]


def test_source_reindex_full_flag_calls_full_reindex(monkeypatch):
    calls = []

    class FakeAPI:
        def get_source(self, source_id):
            return {"id": source_id, "name": "Docs", "root_path": "/data/docs"}

        def reindex_source(self, source_id, full=False):
            calls.append((source_id, full))
            return {"stats": {"total_scanned": 1, "successful": 1}}

    monkeypatch.setattr(Context, "get_api", lambda self: FakeAPI())

    runner = CliRunner()
    result = runner.invoke(cli, ["source", "reindex", "docs", "--full"], obj=Context())

    assert result.exit_code == 0
    assert calls == [("docs", True)]
    assert "Full reindexing source" in result.output
