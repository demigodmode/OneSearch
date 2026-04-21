from urllib.parse import urlparse

import pytest
import requests
from click.testing import CliRunner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import hash_password
from app.db.database import get_db
from app.main import app
from app.models import Base, User
from onesearch.config import get_auth_token
from onesearch.context import Context
from onesearch.main import cli

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ResponseAdapter:
    def __init__(self, response):
        self.status_code = response.status_code
        self.content = response.content
        self._response = response

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return self._response.json()


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def backend_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session):
    user = User(
        username="testuser",
        password_hash=hash_password("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def cli_backend(monkeypatch, backend_client):
    def fake_request(session_self, method, url, params=None, json=None, timeout=None, **kwargs):
        parsed = urlparse(url)
        headers = dict(session_self.headers)
        headers.update(kwargs.get("headers") or {})
        response = backend_client.request(method, parsed.path, params=params, json=json, headers=headers)
        return ResponseAdapter(response)

    monkeypatch.setattr(requests.Session, "request", fake_request)


def test_login_stores_token_and_whoami_uses_it(cli_backend, sample_user, monkeypatch, tmp_path):
    monkeypatch.delenv("ONESEARCH_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    runner = CliRunner()

    login_result = runner.invoke(
        cli,
        ["--url", "http://testserver", "login"],
        input="testuser\ntestpass\n",
        obj=Context(),
    )
    assert login_result.exit_code == 0
    assert get_auth_token()

    whoami_result = runner.invoke(cli, ["--url", "http://testserver", "whoami"], obj=Context())
    assert whoami_result.exit_code == 0
    assert "testuser" in whoami_result.output


def test_whoami_without_token_shows_actionable_error(cli_backend, sample_user, monkeypatch, tmp_path):
    monkeypatch.delenv("ONESEARCH_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli, ["--url", "http://testserver", "whoami"], obj=Context())
    assert result.exit_code == 1
    assert "onesearch login" in result.output
