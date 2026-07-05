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


@pytest.fixture
def client_with_scheduler(db_session, test_user):
    """Create test client with scheduler attached to app state"""
    from sqlalchemy.orm import sessionmaker
    from app.services.scheduler import calculate_next_run_time_for_schedule

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Create mock scheduler that uses the same engine as the test session
    class MockScheduler:
        def __init__(self, engine):
            self.engine = engine
            self._session_factory = sessionmaker(bind=engine)

        def update_source_schedule(self, source_id):
            """Simulate scheduler updating next_scan_at by opening a new session"""
            from app.models import Source
            from app.services.scheduler import resolve_effective_schedule

            db = self._session_factory()
            try:
                source = db.get(Source, source_id)
                if not source:
                    return

                resolved = resolve_effective_schedule(source, db)

                # Only set next_scan_at if schedule is not manual
                schedule_type = resolved.get("schedule_type")
                if schedule_type == "interval":
                    from app.services.scheduler import validate_interval
                    if not validate_interval(resolved.get("interval_value"), resolved.get("interval_unit")):
                        return
                    next_time = calculate_next_run_time_for_schedule(
                        "interval", None, resolved.get("interval_value"), resolved.get("interval_unit")
                    )
                else:
                    scan_schedule = resolved.get("scan_schedule")
                    if not scan_schedule:
                        next_time = None
                    else:
                        next_time = calculate_next_run_time_for_schedule(
                            "cron", scan_schedule, None, None
                        )

                source.next_scan_at = next_time
                db.commit()
            finally:
                db.close()

    mock_scheduler = MockScheduler(db_session.get_bind())

    app.dependency_overrides[get_db] = override_get_db

    # Attach mock scheduler to app state
    with TestClient(app) as test_client:
        test_client.app.state.scheduler = mock_scheduler
        test_client.headers.update(test_user["headers"])
        yield test_client

    app.dependency_overrides.clear()
    # Clean up scheduler attachment
    if hasattr(app.state, "scheduler"):
        delattr(app.state, "scheduler")
