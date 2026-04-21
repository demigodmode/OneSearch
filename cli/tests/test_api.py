import pytest
import requests

from onesearch.api import APIError, OneSearchAPI


class DummyResponse:
    def __init__(self, status_code=401, detail="Not authenticated"):
        self.status_code = status_code
        self._detail = detail
        self.content = b'{"detail":"%s"}' % detail.encode()

    def raise_for_status(self):
        raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return {"detail": self._detail}


def test_api_client_sets_bearer_token():
    api = OneSearchAPI(base_url="http://localhost:8000", token="secret")
    assert api.session.headers["Authorization"] == "Bearer secret"


def test_auth_error_message_is_actionable(monkeypatch):
    api = OneSearchAPI(base_url="http://localhost:8000")

    def fake_request(**kwargs):
        return DummyResponse()

    monkeypatch.setattr(api.session, "request", fake_request)

    with pytest.raises(APIError) as exc:
        api._request("GET", "/api/status")

    assert "onesearch login" in exc.value.message
