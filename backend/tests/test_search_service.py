# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for MeilisearchService - mocked, no running instance needed
"""
import json
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.search import MeilisearchService, INDEX_NAME


def _fake_task(**kwargs):
    """Create a fake task result that behaves like meilisearch TaskInfo"""
    return SimpleNamespace(**kwargs)


@pytest.fixture
def service():
    return MeilisearchService()


@pytest.fixture
def connected_service():
    """Service with mocked client and index"""
    svc = MeilisearchService()
    svc.client = Mock()
    svc.index = Mock()
    return svc


class TestConnect:

    @patch("app.services.search.Client")
    def test_connect_success_existing_index(self, MockClient, service):
        mock_client = MockClient.return_value
        mock_client.health.return_value = {"status": "available"}
        mock_index = Mock()
        mock_client.get_index.return_value = mock_index

        result = service.connect()

        assert result is True
        assert service.client is mock_client
        assert service.index is mock_index
        mock_client.health.assert_called_once()
        mock_index.update_searchable_attributes.assert_called_once()

    @patch("app.services.search.Client")
    def test_connect_creates_index_when_missing(self, MockClient, service):
        mock_client = MockClient.return_value
        mock_client.health.return_value = {"status": "available"}
        mock_client.get_index.side_effect = [Exception("not found"), Mock()]
        mock_task = _fake_task(task_uid=123)
        mock_client.create_index.return_value = mock_task

        result = service.connect()

        assert result is True
        mock_client.create_index.assert_called_once_with(INDEX_NAME, {"primaryKey": "id"})

    @patch("app.services.search.Client")
    def test_connect_health_check_failure(self, MockClient, service):
        mock_client = MockClient.return_value
        mock_client.health.side_effect = Exception("connection refused")

        result = service.connect()

        assert result is False
        assert service.index is None


class TestHealthCheck:

    def test_health_check_connected(self, connected_service):
        connected_service.client.health.return_value = {"status": "available"}
        mock_stats = Mock()
        mock_stats.number_of_documents = 42
        mock_stats.is_indexing = False
        connected_service.index.get_stats.return_value = mock_stats

        result = connected_service.health_check()

        assert result["status"] == "available"
        assert result["document_count"] == 42
        assert result["is_indexing"] is False

    def test_health_check_disconnected(self, service):
        result = service.health_check()

        assert result["status"] == "disconnected"
        assert "error" in result

    def test_health_check_error(self, connected_service):
        connected_service.client.health.side_effect = Exception("timeout")

        result = connected_service.health_check()

        assert result["status"] == "error"
        assert "timeout" in result["error"]

    def test_health_check_dict_response(self, connected_service):
        """Handle Meilisearch returning dicts instead of objects"""
        connected_service.client.health.return_value = {"status": "available"}
        connected_service.index.get_stats.return_value = {
            "numberOfDocuments": 10,
            "isIndexing": True,
        }

        result = connected_service.health_check()

        assert result["document_count"] == 10
        assert result["is_indexing"] is True


class TestIndexDocuments:

    @pytest.mark.asyncio
    async def test_index_pydantic_models(self, connected_service):
        mock_doc = Mock()
        mock_doc.model_dump.return_value = {"id": "doc1", "content": "hello"}
        task = _fake_task(task_uid=1)
        connected_service.index.add_documents.return_value = task

        result = await connected_service.index_documents([mock_doc])

        assert result["task_uid"] == 1
        connected_service.index.add_documents.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_dicts(self, connected_service):
        task = _fake_task(task_uid=2)
        connected_service.index.add_documents.return_value = task

        result = await connected_service.index_documents([{"id": "doc2", "content": "test"}])

        assert result["task_uid"] == 2

    @pytest.mark.asyncio
    async def test_index_not_initialized(self, service):
        with pytest.raises(RuntimeError, match="Index not initialized"):
            await service.index_documents([{"id": "x"}])


class TestDeleteDocument:

    @pytest.mark.asyncio
    async def test_delete_success(self, connected_service):
        task = _fake_task(task_uid=5)
        connected_service.index.delete_document.return_value = task

        result = await connected_service.delete_document("doc1")

        assert result["task_uid"] == 5
        connected_service.index.delete_document.assert_called_once_with("doc1")

    @pytest.mark.asyncio
    async def test_delete_not_initialized(self, service):
        with pytest.raises(RuntimeError, match="Index not initialized"):
            await service.delete_document("doc1")


class TestDeleteDocumentsByFilter:

    @pytest.mark.asyncio
    async def test_delete_by_filter_uses_supported_client_method(self, service):
        class FakeIndex:
            def __init__(self):
                self.filter = None

            def delete_documents(self, *, filter):
                self.filter = filter
                return _fake_task(task_uid=6)

        fake_index = FakeIndex()
        service.index = fake_index

        result = await service.delete_documents_by_filter("source_id = 'src1'")

        assert result["task_uid"] == 6
        assert fake_index.filter == "source_id = 'src1'"

    @pytest.mark.asyncio
    async def test_delete_by_filter_not_initialized(self, service):
        with pytest.raises(RuntimeError, match="Index not initialized"):
            await service.delete_documents_by_filter("source_id = 'src1'")


class TestGetDocument:

    @pytest.mark.asyncio
    async def test_get_document_found(self, connected_service):
        connected_service.index.get_document.return_value = {"id": "doc1", "content": "hi"}

        result = await connected_service.get_document("doc1")

        assert result["id"] == "doc1"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, connected_service):
        import meilisearch.errors

        # Build a proper mock response that MeilisearchApiError can parse
        mock_response = Mock()
        mock_response.text = json.dumps({
            "message": "Document not found",
            "code": "document_not_found",
            "type": "invalid_request",
            "link": "",
        })
        mock_response.status_code = 404
        err = meilisearch.errors.MeilisearchApiError("not found", mock_response)

        connected_service.index.get_document.side_effect = err

        result = await connected_service.get_document("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_document_not_initialized(self, service):
        with pytest.raises(RuntimeError, match="Index not initialized"):
            await service.get_document("doc1")


class TestSearch:

    @pytest.mark.asyncio
    async def test_search_success(self, connected_service):
        connected_service.index.search.return_value = {
            "hits": [{"id": "doc1"}],
            "estimatedTotalHits": 1,
            "processingTimeMs": 5,
        }

        result = await connected_service.search("hello", filters=["source_id = 'src1'"])

        assert result["hits"][0]["id"] == "doc1"
        connected_service.index.search.assert_called_once()
        call_args = connected_service.index.search.call_args
        assert call_args[0][0] == "hello"
        assert call_args[0][1]["filter"] == ["source_id = 'src1'"]

    @pytest.mark.asyncio
    async def test_search_not_initialized(self, service):
        with pytest.raises(RuntimeError, match="Index not initialized"):
            await service.search("test")


class TestConfigureIndex:

    @patch("app.services.search.Client")
    def test_configure_called_during_connect(self, MockClient, service):
        mock_client = MockClient.return_value
        mock_client.health.return_value = {"status": "available"}
        mock_index = Mock()
        mock_client.get_index.return_value = mock_index

        service.connect()

        mock_index.update_searchable_attributes.assert_called_once()
        mock_index.update_filterable_attributes.assert_called_once()
        mock_index.update_sortable_attributes.assert_called_once()
        mock_index.update_ranking_rules.assert_called_once()

    def test_configure_handles_failure(self, connected_service):
        connected_service.index.update_searchable_attributes.side_effect = Exception("nope")

        # Should not raise
        connected_service._configure_index()

    def test_configure_no_index(self, service):
        # Should not raise when index is None
        service._configure_index()
