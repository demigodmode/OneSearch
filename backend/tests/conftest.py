# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Shared test fixtures for OneSearch backend tests.
"""
import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.models import ROLE_ADMIN, ROLE_MEMBER, Base, Source, User
from app.db.database import get_db
from app.config import settings
from app.api.auth import hash_password, create_access_token


@pytest.fixture(autouse=True)
def generated_session_secret_in_tmp(tmp_path_factory):
    """Keep the generated session key out of /app/data during tests."""
    import app.api.auth as auth_module
    # Not tmp_path: some tests check their tmp dir is empty after cleanup.
    secret_path = tmp_path_factory.mktemp("secret") / "session_secret"
    # Own MonkeyPatch, so a test calling monkeypatch.undo() doesn't swap the key mid-test.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(auth_module, "_session_secret_path", lambda: secret_path)
        mp.setattr(auth_module, "_generated_secret", None)
        yield


@pytest.fixture(autouse=True)
def _no_startup_purge_on_the_configured_db(monkeypatch):
    # The app's own scheduler uses DATABASE_URL, not the test database, so keep
    # its startup audit purge from deleting rows in whatever database that is.
    import app.main as main
    from app.services.scheduler import SchedulerService

    class TestScheduler(SchedulerService):
        def _purge_audit_log(self, now=None):
            return None

    monkeypatch.setattr(main, "SchedulerService", TestScheduler)


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


@contextmanager
def _signed_in_client(db_session, headers: dict[str, str]):
    """TestClient that reads from db_session and sends headers on every request"""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.headers.update(headers)
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    """Create a test user and return auth headers"""
    user = User(
        username="testuser",
        password_hash=hash_password("testpass"),
        is_active=True,
        role=ROLE_ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token, _ = create_access_token(user.id, user.username, user.session_version)
    return {
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def member_user(db_session):
    """A signed-in user with the member role, created directly in the database"""
    user = User(
        username="member",
        password_hash=hash_password("memberpass"),
        is_active=True,
        role=ROLE_MEMBER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def member_client(db_session, member_user):
    """Test client signed in as the member user"""
    token, _ = create_access_token(member_user.id, member_user.username, member_user.session_version)
    with _signed_in_client(db_session, {"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(test_user):
    """Get auth headers for authenticated requests"""
    return test_user["headers"]


@pytest.fixture
def client(db_session, test_user):
    """Create test client with database dependency override and auth"""
    with _signed_in_client(db_session, test_user["headers"]) as test_client:
        yield test_client


@pytest.fixture
def meili_spy():
    """Stub bound to app.services.search.meili_service so tests don't need a real
    Meilisearch server. Records wait_for_task calls and can be told to fail the
    next (or Nth) filtered delete, so retry-on-failure paths can be exercised.
    """
    from app.services.search import meili_service

    class MeiliSpy:
        def __init__(self):
            self.waited_for_tasks = 0
            self.filter_delete_calls = 0
            self._fail_next = False
            self._fail_on_call = None

        def fail_next_filter_delete(self):
            self._fail_next = True

        def fail_filter_delete_on_call(self, n):
            self._fail_on_call = n

        async def delete_documents_by_filter_confirmed(self, filter_str):
            self.filter_delete_calls += 1
            should_fail = self._fail_next or self._fail_on_call == self.filter_delete_calls
            self._fail_next = False
            if should_fail:
                raise RuntimeError("simulated Meilisearch delete failure")
            self.waited_for_tasks += 1
            return {"status": "succeeded"}

    spy = MeiliSpy()
    original = meili_service.delete_documents_by_filter_confirmed
    meili_service.delete_documents_by_filter_confirmed = spy.delete_documents_by_filter_confirmed
    try:
        yield spy
    finally:
        meili_service.delete_documents_by_filter_confirmed = original


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
            self.sync_default_schedule_sources_calls = 0

        def sync_default_schedule_sources(self):
            """Track calls so tests can assert the resync was triggered"""
            self.sync_default_schedule_sources_calls += 1

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
