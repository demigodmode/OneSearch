"""
Tests for indexing service
"""
import pytest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Source, IndexedFile
from app.services.indexer import IndexingService, IndexingStats
from app.schemas import Document


@pytest.fixture
def db_session():
    """Create in-memory database session for testing"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()


@pytest.fixture
def mock_search_service():
    """Create mock search service"""
    service = Mock()
    service.index_documents = AsyncMock(return_value={"task_uid": "test123"})
    service.delete_document = AsyncMock(return_value={"task_uid": "test456"})
    return service


@pytest.fixture
def test_source(db_session):
    """Create test source in database"""
    source = Source(
        id="test_source",
        name="Test Source",
        root_path="/tmp/test",
        include_patterns=json.dumps(["**/*.txt"]),
        exclude_patterns=json.dumps([])
    )
    db_session.add(source)
    db_session.commit()
    return source


@pytest.fixture
def test_directory():
    """Create test directory with sample files"""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create test files
        (tmp_path / "file1.txt").write_text("Content of file 1")
        (tmp_path / "file2.txt").write_text("Content of file 2")
        (tmp_path / "file3.md").write_text("# Markdown file")

        yield tmp_path


class TestIndexingStats:
    """Tests for IndexingStats"""

    def test_initial_state(self):
        """Test initial state of stats"""
        stats = IndexingStats()

        assert stats.total_scanned == 0
        assert stats.new_files == 0
        assert stats.modified_files == 0
        assert stats.successful == 0
        assert stats.failed == 0

    def test_to_dict(self):
        """Test conversion to dictionary"""
        stats = IndexingStats()
        stats.total_scanned = 10
        stats.successful = 8
        stats.failed = 2

        data = stats.to_dict()

        assert data["total_scanned"] == 10
        assert data["successful"] == 8
        assert data["failed"] == 2
        assert "errors" in data


class TestIndexingService:
    """Tests for IndexingService"""

    @pytest.mark.asyncio
    async def test_index_source_not_found(self, db_session, mock_search_service):
        """Test indexing with nonexistent source"""
        service = IndexingService(db_session, mock_search_service)

        with pytest.raises(ValueError, match="Source not found"):
            await service.index_source("nonexistent")

    @pytest.mark.asyncio
    async def test_check_needs_indexing_new_file(self, db_session, test_directory):
        """Test checking if new file needs indexing"""
        service = IndexingService(db_session, Mock())

        file_path = str(test_directory / "file1.txt")
        needs_indexing, reason = service._check_needs_indexing(file_path, {})

        assert needs_indexing is True
        assert reason == "new"

    @pytest.mark.asyncio
    async def test_check_needs_indexing_unchanged_file(self, db_session, test_directory):
        """Test checking if unchanged file needs indexing"""
        service = IndexingService(db_session, Mock())

        file_path = str(test_directory / "file1.txt")
        path = Path(file_path)
        stat = path.stat()

        # Create indexed file record with same size and mtime
        indexed_file = IndexedFile(
            source_id="test_source",
            path=file_path,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            indexed_at=datetime.utcnow(),
            status="success"
        )

        indexed_files_map = {file_path: indexed_file}
        needs_indexing, reason = service._check_needs_indexing(
            file_path, indexed_files_map
        )

        assert needs_indexing is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_check_needs_indexing_modified_file(self, db_session, test_directory):
        """Test checking if modified file needs indexing"""
        service = IndexingService(db_session, Mock())

        file_path = str(test_directory / "file1.txt")

        # Create indexed file record with different size
        indexed_file = IndexedFile(
            source_id="test_source",
            path=file_path,
            size_bytes=999,  # Different from actual size
            modified_at=datetime.fromtimestamp(0),
            indexed_at=datetime.utcnow(),
            status="success"
        )

        indexed_files_map = {file_path: indexed_file}
        needs_indexing, reason = service._check_needs_indexing(
            file_path, indexed_files_map
        )

        assert needs_indexing is True
        assert reason == "modified"

    @pytest.mark.asyncio
    async def test_update_indexed_file_new(self, db_session):
        """Test creating new indexed file record"""
        service = IndexingService(db_session, Mock())

        with TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test.txt"
            file_path.write_text("test content")

            service._update_indexed_file(
                "test_source",
                str(file_path),
                status="success"
            )

            # Check record was created
            indexed_files = db_session.query(IndexedFile).all()
            assert len(indexed_files) == 1
            assert indexed_files[0].path == str(file_path)
            assert indexed_files[0].status == "success"

    @pytest.mark.asyncio
    async def test_update_indexed_file_existing(self, db_session):
        """Test updating existing indexed file record"""
        service = IndexingService(db_session, Mock())

        with TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test.txt"
            file_path.write_text("test content")

            # Create initial record
            indexed_file = IndexedFile(
                source_id="test_source",
                path=str(file_path),
                size_bytes=100,
                modified_at=datetime.utcnow(),
                indexed_at=datetime.utcnow(),
                status="success"
            )
            db_session.add(indexed_file)
            db_session.commit()

            # Update with new status
            service._update_indexed_file(
                "test_source",
                str(file_path),
                status="failed",
                error="Test error"
            )

            # Check record was updated
            updated = db_session.query(IndexedFile).filter_by(
                source_id="test_source",
                path=str(file_path)
            ).first()

            assert updated.status == "failed"
            assert updated.error_message == "Test error"

    @pytest.mark.asyncio
    async def test_get_source_status(self, db_session, test_source):
        """Test getting source status"""
        service = IndexingService(db_session, Mock())

        # Add some indexed files
        indexed_file1 = IndexedFile(
            source_id="test_source",
            path="/tmp/file1.txt",
            size_bytes=100,
            modified_at=datetime.utcnow(),
            indexed_at=datetime.utcnow(),
            status="success"
        )
        indexed_file2 = IndexedFile(
            source_id="test_source",
            path="/tmp/file2.txt",
            size_bytes=200,
            modified_at=datetime.utcnow(),
            indexed_at=datetime.utcnow(),
            status="failed",
            error_message="Test error"
        )
        db_session.add_all([indexed_file1, indexed_file2])
        db_session.commit()

        # Get status
        status = service.get_source_status("test_source")

        assert status["source_id"] == "test_source"
        assert status["source_name"] == "Test Source"
        assert status["total_files"] == 2
        assert status["successful"] == 1
        assert status["failed"] == 1
        assert len(status["failed_files"]) == 1

    @pytest.mark.asyncio
    async def test_extract_document_unsupported_type(self, db_session):
        """Test extracting document with unsupported file type"""
        service = IndexingService(db_session, Mock())

        with TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test.unsupported"
            file_path.write_text("test content")

            doc = await service._extract_document(
                str(file_path),
                "test_source",
                "Test Source"
            )

            assert doc is None

    @pytest.mark.asyncio
    async def test_update_indexed_file_missing_file(self, db_session):
        """Test handling of files that disappear during indexing"""
        service = IndexingService(db_session, Mock())

        # Try to update a file that doesn't exist
        service._update_indexed_file(
            "test_source",
            "/nonexistent/file.txt",
            status="success"
        )

        # Should create record with failed status
        indexed_file = db_session.query(IndexedFile).filter_by(
            source_id="test_source",
            path="/nonexistent/file.txt"
        ).first()

        assert indexed_file is not None
        assert indexed_file.status == "failed"
        assert "File not found" in indexed_file.error_message
        assert indexed_file.size_bytes == 0

    @pytest.mark.asyncio
    @patch('app.services.indexer.FileScanner')
    async def test_index_source_full_flow(
        self,
        mock_scanner_class,
        db_session,
        mock_search_service,
        test_directory
    ):
        """Test full indexing flow"""
        # Setup mock scanner
        mock_scanner = Mock()
        mock_scanner.scan.return_value = [
            str(test_directory / "file1.txt"),
            str(test_directory / "file2.txt"),
        ]
        mock_scanner_class.return_value = mock_scanner

        # Create source with proper root path
        source = Source(
            id="test_source2",
            name="Test Source 2",
            root_path=str(test_directory),
            include_patterns=json.dumps(["**/*.txt"]),
            exclude_patterns=json.dumps([])
        )
        db_session.add(source)
        db_session.commit()

        # Index the source
        service = IndexingService(db_session, mock_search_service)
        stats = await service.index_source("test_source2")

        # Verify stats
        assert stats.total_scanned == 2
        assert stats.new_files == 2
        assert stats.successful == 2
        assert stats.failed == 0

        # Verify documents were indexed
        assert mock_search_service.index_documents.called

        # Verify database records
        indexed_files = db_session.query(IndexedFile).filter_by(
            source_id="test_source2"
        ).all()
        assert len(indexed_files) == 2
