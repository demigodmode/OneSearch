# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for FastAPI API endpoints

IMPORTANT: These tests require Meilisearch to be running for full coverage.
- Start Meilisearch: docker run -p 7700:7700 getmeili/meilisearch:latest
- Or use docker-compose: docker-compose up meilisearch

Tests that depend on Meilisearch will be skipped if it's not available.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token, hash_password
from app.config import settings
from app.db.database import get_db
from app.main import app
from app.models import AppSetting, Base, IndexedFile, Source, User
from app.services.search import meili_service

# In-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def disable_path_restriction():
    """Disable allowed_source_paths check in tests so temp dirs work"""
    original = settings.allowed_source_paths
    settings.allowed_source_paths = ""
    yield
    settings.allowed_source_paths = original


@pytest.fixture
def db_session():
    """Create test database session"""
    # Create tables
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop all tables after test
        Base.metadata.drop_all(bind=engine)


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
    return {"user": user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


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
        # Attach auth headers as default
        test_client.headers.update(test_user["headers"])
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def temp_source_dir():
    """Create temporary directory for test source"""
    with TemporaryDirectory() as tmp:
        # Create some test files
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


@pytest.fixture(scope="session")
def meili_available():
    """Check if Meilisearch is available for testing"""
    try:
        # Check if the index is initialized (not just client exists)
        return meili_service.index is not None
    except:
        return False


class TestHealthEndpoint:
    """Tests for /api/health endpoint"""

    def test_health_check_success(self, client):
        """Test health check returns status info (503 if Meilisearch not running)"""
        response = client.get("/api/health")

        assert response.status_code in (200, 503)
        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert data["service"] == "onesearch-backend"

    def test_health_check_includes_meilisearch_status(self, client):
        """Test health check includes Meilisearch status"""
        response = client.get("/api/health")

        assert response.status_code in (200, 503)
        data = response.json()

        assert "meilisearch" in data
        assert "status" in data["meilisearch"]


class TestSourceEndpoints:
    """Tests for /api/sources endpoints"""

    def test_list_sources_empty(self, client):
        """Test listing sources when none exist"""
        response = client.get("/api/sources")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_sources_with_data(self, client, sample_source):
        """Test listing sources returns existing sources"""
        response = client.get("/api/sources")

        assert response.status_code == 200
        sources = response.json()

        assert len(sources) == 1
        assert sources[0]["id"] == "test-source"
        assert sources[0]["name"] == "Test Source"

    def test_get_source_success(self, client, sample_source):
        """Test getting a specific source by ID"""
        response = client.get(f"/api/sources/{sample_source.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == sample_source.id
        assert data["name"] == sample_source.name
        assert data["root_path"] == sample_source.root_path

    def test_get_source_not_found(self, client):
        """Test getting non-existent source returns 404"""
        response = client.get("/api/sources/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_source_success(self, client, temp_source_dir):
        """Test creating a new source"""
        source_data = {
            "name": "New Test Source",
            "root_path": temp_source_dir,
            "include_patterns": ["**/*.txt"],
            "exclude_patterns": ["**/node_modules/**"],
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == source_data["name"]
        assert "id" in data  # Should have auto-generated ID
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_source_with_custom_id(self, client, temp_source_dir):
        """Test creating source with custom ID"""
        source_data = {
            "id": "custom-id",
            "name": "Custom ID Source",
            "root_path": temp_source_dir,
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 201
        data = response.json()

        assert data["id"] == "custom-id"

    def test_create_source_duplicate_id(self, client, sample_source, temp_source_dir):
        """Test creating source with duplicate ID fails"""
        source_data = {
            "id": sample_source.id,  # Same ID as existing source
            "name": "Duplicate ID Source",
            "root_path": temp_source_dir,
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_source_invalid_path(self, client):
        """Test creating source with non-existent path fails"""
        source_data = {
            "name": "Invalid Path Source",
            "root_path": "/path/that/does/not/exist",
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"].lower()

    def test_create_source_checks_allowed_paths_before_stat(self, client, tmp_path, monkeypatch):
        """Outside allowed roots should not disclose whether the path exists or is a file."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_file = tmp_path / "outside-secret.txt"
        outside_file.write_text("secret")
        monkeypatch.setattr("app.api.sources.settings.allowed_source_paths", str(allowed_dir))

        response = client.post("/api/sources", json={
            "name": "Outside Source",
            "root_path": str(outside_file),
        })

        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "outside allowed" in detail
        assert "not a directory" not in detail
        assert "does not exist" not in detail

    def test_create_source_path_is_file(self, client, temp_source_dir):
        """Test creating source with file path (not directory) fails"""
        file_path = str(Path(temp_source_dir) / "test1.txt")

        source_data = {
            "name": "File Path Source",
            "root_path": file_path,
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 400
        assert "not a directory" in response.json()["detail"].lower()

    def test_update_source_success(self, client, sample_source):
        """Test updating source configuration"""
        update_data = {
            "name": "Updated Source Name",
            "include_patterns": ["**/*.pdf"],
        }

        response = client.put(f"/api/sources/{sample_source.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated Source Name"
        assert data["updated_at"] >= data["created_at"]

    def test_update_source_not_found(self, client):
        """Test updating non-existent source returns 404"""
        update_data = {"name": "New Name"}

        response = client.put("/api/sources/nonexistent", json=update_data)

        assert response.status_code == 404

    def test_update_source_invalid_path(self, client, sample_source):
        """Test updating source with invalid path fails"""
        update_data = {
            "root_path": "/invalid/path",
        }

        response = client.put(f"/api/sources/{sample_source.id}", json=update_data)

        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"].lower()

    def test_delete_source_success(self, client, sample_source, db_session):
        """Test deleting a source"""
        response = client.delete(f"/api/sources/{sample_source.id}")

        assert response.status_code == 204

        # Verify source is deleted
        from sqlalchemy import select
        stmt = select(Source).where(Source.id == sample_source.id)
        result = db_session.execute(stmt).scalar_one_or_none()
        assert result is None

    def test_delete_source_not_found(self, client):
        """Test deleting non-existent source returns 404"""
        response = client.delete("/api/sources/nonexistent")

        assert response.status_code == 404

    def test_delete_source_cascades_indexed_files(self, client, sample_source, db_session):
        """Test deleting source also deletes indexed_files records"""
        # Add some indexed files
        indexed_file = IndexedFile(
            source_id=sample_source.id,
            path="/test/file.txt",
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="success",
        )
        db_session.add(indexed_file)
        db_session.commit()

        # Delete source
        response = client.delete(f"/api/sources/{sample_source.id}")
        assert response.status_code == 204

        # Verify indexed files are also deleted (cascade)
        from sqlalchemy import select
        stmt = select(IndexedFile).where(IndexedFile.source_id == sample_source.id)
        result = db_session.execute(stmt).scalars().all()
        assert len(result) == 0


class TestSourceScheduling:
    """Tests for source scan scheduling"""

    def test_create_source_with_schedule_sets_next_scan(self, client, temp_source_dir):
        """Creating a source with a schedule should set next_scan_at"""
        source_data = {
            "name": "Scheduled Source",
            "root_path": temp_source_dir,
            "scan_schedule": "@hourly",
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 201
        data = response.json()

        assert data["scan_schedule"] == "@hourly"
        assert data["next_scan_at"] is not None
        # Verify it's a valid ISO datetime in the future
        next_scan_str = data["next_scan_at"].replace("Z", "").replace("+00:00", "")
        next_scan = datetime.fromisoformat(next_scan_str)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert next_scan > now

    def test_create_source_without_schedule_no_next_scan(self, client, temp_source_dir):
        """Creating a source without a schedule should not set next_scan_at"""
        source_data = {
            "name": "Manual Source",
            "root_path": temp_source_dir,
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 201
        data = response.json()

        assert data["scan_schedule"] is None
        assert data["next_scan_at"] is None

    def test_update_source_schedule_updates_next_scan(self, client, sample_source):
        """Updating a source's schedule should update next_scan_at immediately"""
        # First verify no schedule
        response = client.get(f"/api/sources/{sample_source.id}")
        assert response.status_code == 200
        assert response.json()["next_scan_at"] is None

        # Add a schedule
        update_data = {"scan_schedule": "@hourly"}
        response = client.put(f"/api/sources/{sample_source.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["scan_schedule"] == "@hourly"
        assert data["next_scan_at"] is not None

    def test_update_source_clear_schedule_clears_next_scan(self, client, temp_source_dir):
        """Clearing a source's schedule should clear next_scan_at"""
        # Create source with schedule
        source_data = {
            "name": "Scheduled Then Manual",
            "root_path": temp_source_dir,
            "scan_schedule": "@daily",
        }
        response = client.post("/api/sources", json=source_data)
        assert response.status_code == 201
        source_id = response.json()["id"]
        assert response.json()["next_scan_at"] is not None

        # Clear the schedule
        update_data = {"scan_schedule": None}
        response = client.put(f"/api/sources/{source_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["scan_schedule"] is None
        assert data["next_scan_at"] is None

    def test_update_source_change_schedule_updates_next_scan(self, client, temp_source_dir):
        """Changing schedule from daily to hourly should update next_scan_at"""
        # Create with daily schedule
        source_data = {
            "name": "Schedule Change Test",
            "root_path": temp_source_dir,
            "scan_schedule": "@daily",
        }
        response = client.post("/api/sources", json=source_data)
        assert response.status_code == 201
        source_id = response.json()["id"]
        daily_next = response.json()["next_scan_at"]

        # Change to hourly
        update_data = {"scan_schedule": "@hourly"}
        response = client.put(f"/api/sources/{source_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["scan_schedule"] == "@hourly"
        hourly_next = data["next_scan_at"]

        # Hourly should be sooner than daily (within an hour vs up to 24 hours)
        hourly_dt = datetime.fromisoformat(hourly_next.replace("Z", "").replace("+00:00", ""))
        daily_dt = datetime.fromisoformat(daily_next.replace("Z", "").replace("+00:00", ""))
        # Hourly next run should be before or equal to daily
        assert hourly_dt <= daily_dt

    def test_create_source_invalid_schedule(self, client, temp_source_dir):
        """Creating a source with invalid schedule should fail"""
        source_data = {
            "name": "Bad Schedule",
            "root_path": temp_source_dir,
            "scan_schedule": "not a valid cron",
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_update_source_invalid_schedule(self, client, sample_source):
        """Updating source with invalid schedule should fail"""
        update_data = {"scan_schedule": "bad cron expression"}

        response = client.put(f"/api/sources/{sample_source.id}", json=update_data)

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_create_source_custom_cron_schedule(self, client, temp_source_dir):
        """Creating a source with custom cron should work"""
        source_data = {
            "name": "Custom Cron Source",
            "root_path": temp_source_dir,
            "scan_schedule": "0 */6 * * *",  # Every 6 hours
        }

        response = client.post("/api/sources", json=source_data)

        assert response.status_code == 201
        data = response.json()

        assert data["scan_schedule"] == "0 */6 * * *"
        assert data["next_scan_at"] is not None


class TestReindexEndpoint:
    """Tests for /api/sources/{id}/reindex endpoint"""

    @pytest.mark.asyncio
    async def test_reindex_source_not_found(self, client):
        """Test reindexing non-existent source returns 404"""
        response = client.post("/api/sources/nonexistent/reindex")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_reindex_uses_overridden_database_session(self, client, sample_source, monkeypatch):
        """Reindexing should use the test database bind, not the app's default DB."""
        from app.api import sources

        class FakeSearchService:
            async def index_documents(self, documents):
                return None

            async def delete_documents_by_filter(self, filter_str):
                return None

        monkeypatch.setattr(sources, "meili_service", FakeSearchService())

        response = client.post(f"/api/sources/{sample_source.id}/reindex")

        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.json()}"

    @pytest.mark.asyncio
    async def test_reindex_source_success(self, client, sample_source, meili_available):
        """Test reindexing returns statistics

        Requires Meilisearch to be running. Will skip if unavailable.
        """
        if not meili_available:
            pytest.skip("Meilisearch not available - start with: docker run -p 7700:7700 getmeili/meilisearch:latest")

        response = client.post(f"/api/sources/{sample_source.id}/reindex")

        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.json()}"

        data = response.json()
        assert "message" in data
        assert "stats" in data
        assert "total_scanned" in data["stats"]
        assert "successful" in data["stats"]
        assert "failed" in data["stats"]


class TestCleanFailedFilesEndpoint:
    """Tests for /api/sources/{id}/clear-stale endpoint"""

    def test_clean_failed_files_removes_missing_file(self, client, sample_source, db_session, monkeypatch):
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(Path(sample_source.root_path) / "missing.txt"),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()
        failed_id = failed.id

        delete_document = AsyncMock(return_value={})
        monkeypatch.setattr("app.api.sources.meili_service.delete_document", delete_document)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 1, "reindexed": 0, "still_failed": 0, "skipped": 0}
        assert db_session.get(IndexedFile, failed_id) is None
        delete_document.assert_awaited_once()

    def test_clean_failed_files_reindexes_existing_file(self, client, sample_source, db_session, monkeypatch):
        path = Path(sample_source.root_path) / "retry.txt"
        path.write_text("retry me")
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(path),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()

        index_documents = AsyncMock(return_value={})
        monkeypatch.setattr("app.api.sources.meili_service.index_documents", index_documents)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 0, "reindexed": 1, "still_failed": 0, "skipped": 0}
        db_session.refresh(failed)
        assert failed.status == "success"
        assert failed.error_message is None
        index_documents.assert_awaited_once()

    def test_clean_failed_files_clears_existing_file_now_excluded(self, client, sample_source, db_session, monkeypatch):
        path = Path(sample_source.root_path) / "excluded.txt"
        path.write_text("excluded")
        sample_source.exclude_patterns = json.dumps(["**/excluded.txt"])
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(path),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()
        failed_id = failed.id

        delete_document = AsyncMock(return_value={})
        index_documents = AsyncMock(return_value={})
        monkeypatch.setattr("app.api.sources.meili_service.delete_document", delete_document)
        monkeypatch.setattr("app.api.sources.meili_service.index_documents", index_documents)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 1, "reindexed": 0, "still_failed": 0, "skipped": 0}
        assert db_session.get(IndexedFile, failed_id) is None
        delete_document.assert_awaited_once()
        index_documents.assert_not_awaited()

    def test_clean_failed_files_clears_existing_file_outside_current_root(self, client, sample_source, db_session, tmp_path, monkeypatch):
        old_path = Path(sample_source.root_path) / "old-root.txt"
        old_path.write_text("old root")
        new_root = tmp_path / "new-root"
        new_root.mkdir()
        sample_source.root_path = str(new_root)
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(old_path),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()
        failed_id = failed.id

        delete_document = AsyncMock(return_value={})
        index_documents = AsyncMock(return_value={})
        monkeypatch.setattr("app.api.sources.meili_service.delete_document", delete_document)
        monkeypatch.setattr("app.api.sources.meili_service.index_documents", index_documents)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 1, "reindexed": 0, "still_failed": 0, "skipped": 0}
        assert db_session.get(IndexedFile, failed_id) is None
        delete_document.assert_awaited_once()
        index_documents.assert_not_awaited()

    def test_clean_failed_files_returns_conflict_when_source_is_indexing(self, client, sample_source):
        from app.services.scheduler import get_source_lock

        lock = get_source_lock(sample_source.id)
        assert lock.acquire(blocking=False)
        try:
            response = client.post(f"/api/sources/{sample_source.id}/clear-stale")
        finally:
            lock.release()

        assert response.status_code == 409
        assert response.json()["detail"] == f"Indexing already in progress for source '{sample_source.id}'"

    def test_clean_failed_files_marks_unsupported_existing_file_as_skipped(self, client, sample_source, db_session):
        db_session.add(AppSetting(key="unsupported_file_policy", value="skip"))
        sample_source.include_patterns = json.dumps(["**/*"])
        path = Path(sample_source.root_path) / "unsupported.binxyz"
        path.write_text("unsupported")
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(path),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 0, "reindexed": 0, "still_failed": 0, "skipped": 1}
        db_session.refresh(failed)
        assert failed.status == "skipped"
        assert failed.error_message == "Unsupported file type"

    def test_clean_failed_files_uses_updated_text_size_limit(self, client, sample_source, db_session, monkeypatch):
        path = Path(sample_source.root_path) / "large.txt"
        path.write_bytes((b"large text searchable after size setting\n" * 32768)[:1_500_000])
        db_session.add(AppSetting(key="max_text_file_size_mb", value="1"))
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(path),
            size_bytes=0,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="File too large",
        )
        db_session.add(failed)
        db_session.commit()

        index_documents = AsyncMock(return_value={})
        monkeypatch.setattr("app.api.sources.meili_service.index_documents", index_documents)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")
        assert response.status_code == 200
        assert response.json() == {"cleared": 0, "reindexed": 0, "still_failed": 1, "skipped": 0}
        db_session.refresh(failed)
        assert failed.status == "failed"
        assert "File too large" in failed.error_message
        index_documents.assert_not_awaited()

        response = client.put("/api/settings", json={"max_text_file_size_mb": 2})
        assert response.status_code == 200

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 0, "reindexed": 1, "still_failed": 0, "skipped": 0}
        db_session.refresh(failed)
        assert failed.status == "success"
        assert failed.error_message is None
        index_documents.assert_awaited_once()

    def test_clean_failed_files_keeps_existing_file_when_retry_fails(self, client, sample_source, db_session, monkeypatch):
        path = Path(sample_source.root_path) / "broken.txt"
        path.write_text("broken")
        failed = IndexedFile(
            source_id=sample_source.id,
            path=str(path),
            size_bytes=100,
            modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="failed",
            error_message="old error",
        )
        db_session.add(failed)
        db_session.commit()

        async def raise_retry_failure(self, file_path, source_id, source_name):
            raise ValueError("still broken")

        monkeypatch.setattr("app.services.indexer.IndexingService._extract_document", raise_retry_failure)

        response = client.post(f"/api/sources/{sample_source.id}/clear-stale")

        assert response.status_code == 200
        assert response.json() == {"cleared": 0, "reindexed": 0, "still_failed": 1, "skipped": 0}
        db_session.refresh(failed)
        assert failed.status == "failed"
        assert failed.error_message == "still broken"


class TestSearchEndpoint:
    """Tests for /api/search endpoint"""

    def test_search_empty_query(self, client):
        """Test search with empty query returns 400"""
        search_query = {"q": ""}

        response = client.post("/api/search", json=search_query)

        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"].lower()

    def test_search_missing_query(self, client):
        """Test search without query string returns 422 (validation error)"""
        search_query = {}

        response = client.post("/api/search", json=search_query)

        assert response.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_search_with_valid_query(self, client, meili_available):
        """Test search with valid query

        Requires Meilisearch to be running. Will skip if unavailable.
        """
        if not meili_available:
            pytest.skip("Meilisearch not available - start with: docker run -p 7700:7700 getmeili/meilisearch:latest")

        search_query = {
            "q": "test query",
            "limit": 20,
            "offset": 0,
        }

        response = client.post("/api/search", json=search_query)

        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.json()}"

        data = response.json()
        assert "results" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "processing_time_ms" in data
        assert isinstance(data["results"], list)

    @pytest.mark.asyncio
    async def test_search_with_filters(self, client, meili_available):
        """Test search with source_id and type filters

        This test validates proper filter quoting/escaping.
        Requires Meilisearch to be running. Will skip if unavailable.
        """
        if not meili_available:
            pytest.skip("Meilisearch not available - start with: docker run -p 7700:7700 getmeili/meilisearch:latest")

        search_query = {
            "q": "test",
            "source_id": "test-source",
            "type": "text",
            "limit": 10,
        }

        response = client.post("/api/search", json=search_query)

        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.json()}"

        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_limit_validation(self, client):
        """Test search limit is validated (1-100)"""
        # Test limit too high
        search_query = {"q": "test", "limit": 200}
        response = client.post("/api/search", json=search_query)
        assert response.status_code == 422  # Validation error

        # Test limit too low
        search_query = {"q": "test", "limit": 0}
        response = client.post("/api/search", json=search_query)
        assert response.status_code == 422


class TestDocumentEndpoint:
    """Tests for /api/documents/{document_id} endpoint"""

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, client, meili_available):
        """Test getting non-existent document returns 404

        Requires Meilisearch to be running. Will skip if unavailable.
        """
        if not meili_available:
            pytest.skip("Meilisearch not available - start with: docker run -p 7700:7700 getmeili/meilisearch:latest")

        response = client.get("/api/documents/nonexistent-doc-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_document_success(self, client, meili_available):
        """Test getting an existing document

        Requires Meilisearch to be running with indexed content.
        Will skip if unavailable.
        """
        if not meili_available:
            pytest.skip("Meilisearch not available - start with: docker run -p 7700:7700 getmeili/meilisearch:latest")

        # First, index a test document
        import asyncio
        test_doc = {
            "id": "test-source--abc123",
            "source_id": "test-source",
            "source_name": "Test Source",
            "path": "/tmp/test.txt",
            "basename": "test.txt",
            "extension": "txt",
            "type": "text",
            "size_bytes": 100,
            "modified_at": 1700000000,
            "indexed_at": 1700000000,
            "content": "This is test content for the document endpoint test.",
            "title": "Test Document",
            "metadata": {}
        }

        # Index the document
        await meili_service.index_documents([test_doc])

        # Wait for indexing to complete
        await asyncio.sleep(0.5)

        # Retrieve the document
        response = client.get(f"/api/documents/{test_doc['id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_doc["id"]
        assert data["content"] == test_doc["content"]
        assert data["path"] == test_doc["path"]
        assert data["type"] == test_doc["type"]

        # Clean up
        await meili_service.delete_document(test_doc["id"])


class TestStatusEndpoint:
    """Tests for /api/status endpoints"""

    def test_get_all_status_empty(self, client):
        """Test getting status with no sources"""
        response = client.get("/api/status")

        assert response.status_code == 200
        data = response.json()

        assert "sources" in data
        assert data["sources"] == []

    def test_get_all_status_with_sources(self, client, sample_source):
        """Test getting status for all sources"""
        response = client.get("/api/status")

        assert response.status_code == 200
        data = response.json()

        assert "sources" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source_id"] == sample_source.id

    def test_get_all_status_does_not_expose_internal_exception(self, client, sample_source, monkeypatch):
        """Partial status fallback should not return raw exception details."""
        class FailingIndexingService:
            def __init__(self, db, search_service):
                pass

            def get_source_status(self, source_id):
                raise RuntimeError("traceback leaked /srv/private/token.txt")

        monkeypatch.setattr("app.api.status.IndexingService", FailingIndexingService)

        response = client.get("/api/status")

        assert response.status_code == 200
        data = response.json()
        assert data["sources"][0]["error"] == "Status unavailable"

    def test_get_source_status_success(self, client, sample_source):
        """Test getting status for specific source"""
        response = client.get(f"/api/status/{sample_source.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["source_id"] == sample_source.id
        assert data["source_name"] == sample_source.name
        assert "total_files" in data
        assert "successful" in data
        assert "failed" in data
        assert "skipped" in data

    def test_get_source_status_not_found(self, client):
        """Test getting status for non-existent source returns 404"""
        response = client.get("/api/status/nonexistent")

        assert response.status_code == 404

    def test_get_source_status_with_indexed_files(self, client, sample_source, db_session):
        """Test status includes counts from indexed_files"""
        # Add some indexed files with different statuses
        files = [
            IndexedFile(
                source_id=sample_source.id,
                path="/test/success.txt",
                size_bytes=100,
                modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="success",
            ),
            IndexedFile(
                source_id=sample_source.id,
                path="/test/failed.txt",
                size_bytes=200,
                modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="failed",
                error_message="Test error",
            ),
            IndexedFile(
                source_id=sample_source.id,
                path="/test/skipped.txt",
                size_bytes=150,
                modified_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="skipped",
            ),
        ]
        for f in files:
            db_session.add(f)
        db_session.commit()

        response = client.get(f"/api/status/{sample_source.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["total_files"] == 3
        assert data["successful"] == 1
        assert data["failed"] == 1
        assert data["skipped"] == 1
        assert len(data["failed_files"]) == 1
        assert data["failed_files"][0]["path"] == "/test/failed.txt"
        assert data["failed_files"][0]["error"] == "Test error"


class TestRootEndpoint:
    """Tests for root / endpoint"""

    def test_root_endpoint(self, client):
        """Test root endpoint returns API information"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert "message" in data
        assert "version" in data
        assert "docs" in data
        assert data["message"] == "OneSearch API"
