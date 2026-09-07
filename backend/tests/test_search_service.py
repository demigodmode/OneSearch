# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for MeilisearchService - mocked, no running instance needed
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models import Agent, AppSetting, Source
from app.schemas import Document
from app.services.agent_auth import AGENT_ONLINE_MAX_AGE
from app.services.search import INDEX_NAME, MeilisearchService, meili_service


def _fake_task(**kwargs):
    """Create a fake task result that behaves like meilisearch TaskInfo"""
    return SimpleNamespace(**kwargs)


@pytest.mark.asyncio
async def test_confirmed_index_and_delete_require_successful_tasks(connected_service):
    connected_service.index_documents = AsyncMock(return_value={"task_uid": 7})
    connected_service.delete_document = AsyncMock(return_value={"task_uid": 8})
    connected_service.client.wait_for_task.return_value = {"status": "succeeded"}
    await connected_service.index_documents_confirmed([{"id": "x"}])
    await connected_service.delete_document_confirmed("x")
    connected_service.client.wait_for_task.return_value = SimpleNamespace(status="failed")
    with pytest.raises(RuntimeError, match="indexing task failed"):
        await connected_service.index_documents_confirmed([{"id": "x"}])
    with pytest.raises(RuntimeError, match="delete task failed"):
        await connected_service.delete_document_confirmed("x")


@pytest.mark.asyncio
async def test_confirmed_batch_delete_waits_for_one_successful_task(connected_service):
    connected_service.index.delete_documents.return_value = {"task_uid": 9}
    connected_service.client.wait_for_task.return_value = {"status": "succeeded"}
    await connected_service.delete_documents_confirmed(["a", "b"])
    connected_service.index.delete_documents.assert_called_once_with(["a", "b"])
    connected_service.client.wait_for_task.return_value = {"status": "failed"}
    with pytest.raises(RuntimeError, match="delete task failed"):
        await connected_service.delete_documents_confirmed(["a", "b"])


@pytest.mark.asyncio
async def test_confirmed_batch_delete_accepts_sdk_task_object(connected_service):
    connected_service.index.delete_documents.return_value = SimpleNamespace(task_uid=10)
    connected_service.client.wait_for_task.return_value = SimpleNamespace(status="succeeded")
    await connected_service.delete_documents_confirmed(["a"])
    connected_service.client.wait_for_task.assert_called_once_with(10, timeout_in_ms=30000)


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
        connected_service.client.health.side_effect = Exception("timeout /srv/private/token.txt")

        result = connected_service.health_check()

        assert result["status"] == "error"
        assert result["error"] == "Meilisearch health check failed"

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
    async def test_index_pydantic_models_uses_json_safe_values(self, connected_service):
        doc = Document(
            id="doc-date",
            source_id="src",
            source_name="Source",
            path="/tmp/note.md",
            basename="note.md",
            extension="md",
            type="markdown",
            size_bytes=10,
            modified_at=1,
            indexed_at=2,
            content="note",
            metadata={"frontmatter": {"published": datetime(2026, 6, 5, 12, 30)}},
        )
        task = _fake_task(task_uid=7)
        connected_service.index.add_documents.return_value = task

        await connected_service.index_documents([doc])

        indexed_docs = connected_service.index.add_documents.call_args.args[0]
        assert indexed_docs[0]["metadata"]["frontmatter"]["published"] == "2026-06-05T12:30:00"

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
        mock_response.text = json.dumps(
            {
                "message": "Document not found",
                "code": "document_not_found",
                "type": "invalid_request",
                "link": "",
            }
        )
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


def _fresh(now=None):
    return (now or datetime.now(timezone.utc).replace(tzinfo=None)) - timedelta(seconds=5)


def _stale(now=None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return now - AGENT_ONLINE_MAX_AGE - timedelta(seconds=5)


@pytest.fixture
def meili_available():
    try:
        return meili_service.index is not None
    except Exception:
        return False


@pytest.fixture
def enable_remote_agents(db_session):
    """Turn on the global remote-agents switch for tests exercising agent status."""
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()


def _make_agent(db_session, agent_id, *, status="online", last_seen_at=None):
    agent = Agent(
        id=agent_id,
        name=agent_id,
        platform="linux",
        version="1.0.0",
        protocol_version=1,
        status=status,
        last_seen_at=last_seen_at,
    )
    db_session.add(agent)
    return agent


def _make_source(db_session, source_id, *, agent=None):
    source = Source(
        id=source_id,
        name=source_id,
        root_path=f"/tmp/{source_id}",
        location_type="agent" if agent else "local",
        agent_id=agent.id if agent else None,
        processing_mode="on_agent" if agent else None,
    )
    db_session.add(source)
    return source


def _doc(doc_id, source_id, source_name, *, content, modified_at=1700000000):
    return {
        "id": doc_id,
        "source_id": source_id,
        "source_name": source_name,
        "path": f"/tmp/{doc_id}.txt",
        "basename": f"{doc_id}.txt",
        "extension": "txt",
        "type": "text",
        "size_bytes": 100,
        "modified_at": modified_at,
        "indexed_at": modified_at,
        "content": content,
        "title": doc_id,
        "metadata": {},
    }


@pytest.mark.asyncio
class TestSearchAvailabilityTieBreak:
    """Search results carry a live agent_status and use it as a relevance tie-breaker."""

    async def test_availability_breaks_ties_in_relevance_mode(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        online_agent = _make_agent(db_session, "agent-online-1", status="online", last_seen_at=_fresh())
        offline_agent = _make_agent(db_session, "agent-offline-1", status="offline", last_seen_at=_stale())
        db_session.commit()
        _make_source(db_session, "src-online-1", agent=online_agent)
        _make_source(db_session, "src-offline-1", agent=offline_agent)
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-tie-online", "src-online-1", "Online Source", content="zephyrquokka document one"),
            _doc("d-tie-offline", "src-offline-1", "Offline Source", content="zephyrquokka document two"),
        ])

        response = client.post("/api/search", json={"q": "zephyrquokka"})
        assert response.status_code == 200
        data = response.json()

        results_by_id = {r["id"]: r for r in data["results"]}
        assert results_by_id["d-tie-online"]["agent_status"] == "online"
        assert results_by_id["d-tie-offline"]["agent_status"] == "offline"

        ids = [r["id"] for r in data["results"]]
        assert ids.index("d-tie-online") < ids.index("d-tie-offline")

        await meili_service.delete_documents_confirmed(["d-tie-online", "d-tie-offline"])

    async def test_relevance_still_beats_availability(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        online_agent = _make_agent(db_session, "agent-online-2", status="online", last_seen_at=_fresh())
        offline_agent = _make_agent(db_session, "agent-offline-2", status="offline", last_seen_at=_stale())
        db_session.commit()
        _make_source(db_session, "src-online-2", agent=online_agent)
        _make_source(db_session, "src-offline-2", agent=offline_agent)
        db_session.commit()

        strong_content = "kraxelfinch " * 20
        weak_content = "some other text that only mentions kraxelfinch once at the very end"

        await meili_service.index_documents_confirmed([
            _doc("d-strong-offline", "src-offline-2", "Offline Source", content=strong_content),
            _doc("d-weak-online", "src-online-2", "Online Source", content=weak_content),
        ])

        response = client.post("/api/search", json={"q": "kraxelfinch"})
        assert response.status_code == 200
        data = response.json()

        ids = [r["id"] for r in data["results"]]
        assert ids.index("d-strong-offline") < ids.index("d-weak-online")

        await meili_service.delete_documents_confirmed(["d-strong-offline", "d-weak-online"])

    async def test_explicit_sort_is_not_reordered_by_availability(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        online_agent = _make_agent(db_session, "agent-online-3", status="online", last_seen_at=_fresh())
        offline_agent = _make_agent(db_session, "agent-offline-3", status="offline", last_seen_at=_stale())
        db_session.commit()
        _make_source(db_session, "src-online-3", agent=online_agent)
        _make_source(db_session, "src-offline-3", agent=offline_agent)
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-sort-older-online", "src-online-3", "Online Source",
                 content="mimbletoad sort test", modified_at=1000),
            _doc("d-sort-newer-offline", "src-offline-3", "Offline Source",
                 content="mimbletoad sort test", modified_at=2000),
        ])

        response = client.post("/api/search", json={"q": "mimbletoad", "sort": "modified_at:desc"})
        assert response.status_code == 200
        data = response.json()

        # Newest modified_at first, regardless of the offline agent behind it.
        ids = [r["id"] for r in data["results"]]
        assert ids.index("d-sort-newer-offline") < ids.index("d-sort-older-online")

        await meili_service.delete_documents_confirmed(["d-sort-older-online", "d-sort-newer-offline"])

    async def test_expired_heartbeat_source_reads_as_offline(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        stale_online_agent = _make_agent(
            db_session, "agent-stale-heartbeat", status="online", last_seen_at=_stale()
        )
        db_session.commit()
        _make_source(db_session, "src-stale-heartbeat", agent=stale_online_agent)
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-stale-heartbeat", "src-stale-heartbeat", "Source", content="wobblenectar heartbeat"),
        ])

        response = client.post("/api/search", json={"q": "wobblenectar"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["agent_status"] == "offline"

        await meili_service.delete_documents_confirmed(["d-stale-heartbeat"])

    async def test_local_source_agent_status_is_null(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        _make_source(db_session, "src-local-1")
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-local-1", "src-local-1", "Local Source", content="plumzinger local doc"),
        ])

        response = client.post("/api/search", json={"q": "plumzinger"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["agent_status"] is None

        await meili_service.delete_documents_confirmed(["d-local-1"])

    async def test_missing_agent_source_reads_offline_not_null(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        agent = _make_agent(db_session, "agent-to-delete", status="online", last_seen_at=_fresh())
        db_session.commit()
        _make_source(db_session, "src-missing-agent", agent=agent)
        db_session.commit()

        # Delete the Agent row directly (not via API revoke/delete, which would
        # cascade the Source away too) so the Source is left pointing at nothing.
        db_session.query(Agent).filter(Agent.id == "agent-to-delete").delete()
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-missing-agent", "src-missing-agent", "Source", content="glimmerpotato orphan doc"),
        ])

        response = client.post("/api/search", json={"q": "glimmerpotato"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["agent_status"] == "offline"

        await meili_service.delete_documents_confirmed(["d-missing-agent"])

    async def test_reconnected_agent_reads_online_again(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        agent = _make_agent(db_session, "agent-reconnect", status="online", last_seen_at=_stale())
        db_session.commit()
        _make_source(db_session, "src-reconnect", agent=agent)
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-reconnect", "src-reconnect", "Source", content="turnipwhistle reconnect doc"),
        ])

        response = client.post("/api/search", json={"q": "turnipwhistle"})
        assert response.status_code == 200
        assert response.json()["results"][0]["agent_status"] == "offline"

        # Simulate a heartbeat: agent comes back online with a fresh last_seen_at.
        agent.last_seen_at = _fresh()
        db_session.add(agent)
        db_session.commit()

        response = client.post("/api/search", json={"q": "turnipwhistle"})
        assert response.status_code == 200
        assert response.json()["results"][0]["agent_status"] == "online"

        await meili_service.delete_documents_confirmed(["d-reconnect"])

    async def test_stale_source_row_reads_offline_not_null(
        self, client, db_session, meili_available, enable_remote_agents
    ):
        if not meili_available:
            pytest.skip("Meilisearch not available")

        agent = _make_agent(db_session, "agent-for-stale-source", status="online", last_seen_at=_fresh())
        db_session.commit()
        _make_source(db_session, "src-to-delete", agent=agent)
        db_session.commit()

        await meili_service.index_documents_confirmed([
            _doc("d-stale-source", "src-to-delete", "Source", content="brindlefox stale source doc"),
        ])

        # Delete the Source row directly, leaving the Meili doc behind as a stale
        # index entry pointing at a source_id that no longer exists.
        db_session.query(Source).filter(Source.id == "src-to-delete").delete()
        db_session.commit()

        response = client.post("/api/search", json={"q": "brindlefox"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["agent_status"] == "offline"

        await meili_service.delete_documents_confirmed(["d-stale-source"])


def test_apply_relevance_tiebreak_relevance_dominates():
    from app.api.search import _apply_relevance_tiebreak
    from app.schemas import SearchResult

    def _result(rid, score, agent_status):
        return SearchResult(
            id=rid,
            path=f"/tmp/{rid}.txt",
            basename=f"{rid}.txt",
            source_name="src",
            type="text",
            size_bytes=10,
            modified_at=1700000000,
            snippet="",
            score=score,
            source_id="src-1",
            agent_status=agent_status,
        )

    # (a) higher score offline still beats lower score online: relevance dominates.
    results = [_result("low-online", 0.10, "online"), _result("high-offline", 0.90, "offline")]
    _apply_relevance_tiebreak(results)
    assert [r.id for r in results] == ["high-offline", "low-online"]

    # (b) near-equal scores: online-before-offline tie-break.
    results = [_result("tie-offline", 0.5001, "offline"), _result("tie-online", 0.5004, "online")]
    _apply_relevance_tiebreak(results)
    assert [r.id for r in results] == ["tie-online", "tie-offline"]

    # (c) agent_status=None (local) is treated as available, same as "online".
    results = [_result("tie-offline-2", 0.5001, "offline"), _result("tie-local", 0.5004, None)]
    _apply_relevance_tiebreak(results)
    assert [r.id for r in results] == ["tie-local", "tie-offline-2"]
