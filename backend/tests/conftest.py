# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Shared test fixtures for OneSearch backend tests.
"""
import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.models import Base, Source, User
from app.db.database import get_db
from app.config import settings
from app.api.auth import hash_password, create_access_token


# In-memory SQLite for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture
def db_engine():
    """Shared in-memory engine"""
    return _engine


@pytest.fixture
def db_session():
    """Create test database session with fresh tables"""
    Base.metadata.create_all(bind=_engine)
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def test_user(db_session):
    """Create a test user and return auth headers"""
    user = User(
        username="testuser",
        password_hash=hash_password("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token, _ = create_access_token(user.id, user.username)
    return {
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def auth_headers(test_user):
    """Get auth headers for authenticated requests"""
    return test_user["headers"]


@pytest.fixture
def client(db_session, test_user):
    """Create test client with database dependency override and auth"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        test_client.headers.update(test_user["headers"])
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def temp_source_dir():
    """Create temporary directory with sample test files"""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "test1.txt").write_text("Test file 1 content")
        (tmp_path / "test2.md").write_text("# Test Markdown\n\nSome content")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "test3.txt").write_text("Nested file content")
        yield tmp


@pytest.fixture
def sample_source(db_session, temp_source_dir):
    """Create a sample source in the database"""
    source = Source(
        id="test-source",
        name="Test Source",
        root_path=temp_source_dir,
        include_patterns=json.dumps(["**/*.txt", "**/*.md"]),
        exclude_patterns=json.dumps([]),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source
