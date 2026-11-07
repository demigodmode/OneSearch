import pytest
import requests

from onesearch.api import APIError, OneSearchAPI
from onesearch.config import get_auth_token


class DummyResponse:
    def __init__(self, status_code=401, detail="Not authenticated", payload=None):
        self.status_code = status_code
        self._detail = detail
        self._payload = payload or {"detail": detail}
        self.content = b'{"detail":"%s"}' % detail.encode()

    def raise_for_status(self):
        raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return self._payload


def test_api_client_sets_bearer_token():
    api = OneSearchAPI(base_url="http://localhost:8000", token="secret")
    assert api.session.headers["Authorization"] == "Bearer secret"


def test_api_token_is_sent_unchanged_as_bearer(monkeypatch):
    token = "os_AbCd-efGh_ijKlMnOpQrStUvWxYz0123456789abcdefgh"
    monkeypatch.setenv("ONESEARCH_TOKEN", token)
    api = OneSearchAPI(base_url="http://localhost:8000", token=get_auth_token())
    assert api.session.headers["Authorization"] == f"Bearer {token}"


def test_auth_error_message_is_actionable(monkeypatch):
    api = OneSearchAPI(base_url="http://localhost:8000")

    def fake_request(**kwargs):
        return DummyResponse()

    monkeypatch.setattr(api.session, "request", fake_request)

    with pytest.raises(APIError) as exc:
        api._request("GET", "/api/status")

    assert "onesearch login" in exc.value.message


def test_health_allows_degraded_responses(monkeypatch):
    api = OneSearchAPI(base_url="http://localhost:8000")

    def fake_request(**kwargs):
        return DummyResponse(
            status_code=503,
            detail="degraded",
            payload={"status": "degraded", "version": "0.11.1"},
        )

    monkeypatch.setattr(api.session, "request", fake_request)

    result = api.health(allow_degraded=True)

    assert result["status"] == "degraded"
    assert result["version"] == "0.11.1"
