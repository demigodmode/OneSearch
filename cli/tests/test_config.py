from onesearch.config import get_auth_token, get_backend_url, get_config_value, set_config_value


def test_backend_url_defaults_to_localhost(monkeypatch, tmp_path):
    monkeypatch.delenv("ONESEARCH_URL", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert get_backend_url() == "http://localhost:8000"


def test_auth_token_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("ONESEARCH_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    set_config_value("auth.token", "abc123")
    assert get_config_value("auth.token") == "abc123"
    assert get_auth_token() == "abc123"
