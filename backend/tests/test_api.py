# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for FastAPI API endpoints

IMPORTANT: These tests require Meilisearch to be running for full coverage.
- Start Meilisearch: docker run -p 7700:7700 getmeili/meilisearch:latest
- Or use docker-compose: docker-compose up meilisearch

Tests that depend on Meilisearch will be skipped if it's not available.
"""
import pytest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base, Source, IndexedFile
from app.db.database import get_db
from app.services.search import meili_service


# In-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
def client(db_session):
    """Create test client with database dependency override"""
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
        """Test health check returns 200 with status"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert data["service"] == "onesearch-backend"

    def test_health_check_includes_meilisearch_status(self, client):
        """Test health check includes Meilisearch status"""
        response = client.get("/api/health")

        assert response.status_code == 200
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
        # Verify updated_at changed
        assert data["updated_at"] != data["created_at"]

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
            modified_at=datetime.utcnow(),
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


class TestReindexEndpoint:
    """Tests for /api/sources/{id}/reindex endpoint"""

    @pytest.mark.asyncio
    async def test_reindex_source_not_found(self, client):
        """Test reindexing non-existent source returns 404"""
        response = client.post("/api/sources/nonexistent/reindex")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

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
                modified_at=datetime.utcnow(),
                status="success",
            ),
            IndexedFile(
                source_id=sample_source.id,
                path="/test/failed.txt",
                size_bytes=200,
                modified_at=datetime.utcnow(),
                status="failed",
                error_message="Test error",
            ),
            IndexedFile(
                source_id=sample_source.id,
                path="/test/skipped.txt",
                size_bytes=150,
                modified_at=datetime.utcnow(),
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
