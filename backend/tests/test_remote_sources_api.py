"""Remote source and dispatcher boundaries."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.sources import _remote_path_authorized
from app.models import Agent, AgentJob, AppSetting, Source
from app.services.agent_auth import hash_token
from app.services.scan_dispatcher import ScanDispatcher, SourceNotFoundError
from app.services.scheduler import SchedulerService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def approved_agent(db_session):
    agent = Agent(
        id="remote-agent",
        name="Remote",
        platform="linux",
        version="1",
        protocol_version=1,
        token_hash=hash_token("credential"),
        allowed_roots=json.dumps([{"root_id": "docs", "path": "/srv/docs"}]),
        default_processing_mode="on_server",
        status="offline",
        approved_at=_now(),
    )
    db_session.add_all([agent, AppSetting(key="remote_agents_enabled", value="true")])
    db_session.commit()
    return agent


def test_remote_source_create_preserves_authorized_path_and_inherits_mode(
    client, db_session, approved_agent
):
    response = client.post(
        "/api/sources",
        json={
            "id": "remote-source",
            "name": "Remote source",
            "root_path": "/srv/docs/team",
            "location_type": "agent",
            "agent_id": approved_agent.id,
            "processing_mode": None,
        },
    )
    assert response.status_code == 201, response.text
    source = db_session.get(Source, "remote-source")
    assert source.root_path == "/srv/docs/team" and source.processing_mode is None


def test_remote_source_rejects_unapproved_or_outside_path(client, db_session, approved_agent):
    approved_agent.approved_at = None
    db_session.commit()
    response = client.post(
        "/api/sources",
        json={
            "name": "No",
            "root_path": "/srv/docs2",
            "location_type": "agent",
            "agent_id": approved_agent.id,
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "status,approved,credential",
    [
        ("pending", True, True),
        ("disabled", True, True),
        ("revoked", True, True),
        ("online", False, True),
        ("online", True, False),
    ],
)
def test_remote_create_rejects_non_active_agent(
    client, db_session, approved_agent, status, approved, credential
):
    approved_agent.status = status
    approved_agent.approved_at = _now() if approved else None
    approved_agent.token_hash = hash_token("credential") if credential else None
    db_session.commit()
    response = client.post(
        "/api/sources",
        json={
            "name": "No",
            "root_path": "/srv/docs",
            "location_type": "agent",
            "agent_id": approved_agent.id,
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize("path", ["/srv/docs2", "/srv/docs/../secret", " /srv/docs "])
def test_remote_create_rejects_lexically_unauthorized_paths(client, approved_agent, path):
    response = client.post(
        "/api/sources",
        json={
            "name": "No",
            "root_path": path,
            "location_type": "agent",
            "agent_id": approved_agent.id,
        },
    )
    assert response.status_code == 422


def test_remote_create_disabled_and_invalid_mode(client, db_session, approved_agent):
    db_session.query(AppSetting).filter_by(key="remote_agents_enabled").update({"value": "false"})
    db_session.commit()
    disabled = client.post(
        "/api/sources",
        json={
            "name": "No",
            "root_path": "/srv/docs",
            "location_type": "agent",
            "agent_id": approved_agent.id,
        },
    )
    assert disabled.status_code == 409
    invalid = client.post(
        "/api/sources",
        json={
            "name": "No",
            "root_path": "/srv/docs",
            "location_type": "agent",
            "agent_id": approved_agent.id,
            "processing_mode": "invalid",
        },
    )
    assert invalid.status_code == 422


def test_remote_path_test_requires_online_then_queues_and_coalesces(
    client, db_session, approved_agent
):
    offline = client.post(
        "/api/sources/test-path",
        json={"location_type": "agent", "agent_id": approved_agent.id, "root_path": "/srv/docs"},
    )
    assert offline.status_code == 409 and offline.json()["detail"] == "agent_offline"
    approved_agent.status = "online"
    db_session.commit()
    first = client.post(
        "/api/sources/test-path",
        json={"location_type": "agent", "agent_id": approved_agent.id, "root_path": "/srv/docs"},
    )
    second = client.post(
        "/api/sources/test-path",
        json={"location_type": "agent", "agent_id": approved_agent.id, "root_path": "/srv/docs"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["ok"] is False and first.json()["status"] == "pending"


def test_remote_update_validates_prospective_binding_and_disabled_maintenance(
    client, db_session, approved_agent
):
    source = Source(
        id="remote-update",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
    )
    db_session.add(source)
    db_session.commit()
    rejected = client.put("/api/sources/remote-update", json={"root_path": "/outside"})
    assert rejected.status_code == 422
    db_session.query(AppSetting).filter_by(key="remote_agents_enabled").update({"value": "false"})
    db_session.commit()
    maintenance = client.put("/api/sources/remote-update", json={"name": "Renamed"})
    assert maintenance.status_code == 200


def test_remote_manual_scan_is_queued_and_coalesced(client, db_session, approved_agent):
    source = Source(
        id="remote-source",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
    )
    db_session.add(source)
    db_session.commit()
    first = client.post("/api/sources/remote-source/reindex")
    second = client.post("/api/sources/remote-source/reindex")
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["coalesced"] is True


def test_remote_manual_scan_rejects_disabled_feature_without_job(
    client, db_session, approved_agent
):
    source = Source(
        id="disabled-manual",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
    )
    db_session.add(source)
    db_session.query(AppSetting).filter_by(key="remote_agents_enabled").update({"value": "false"})
    db_session.commit()
    response = client.post(f"/api/sources/{source.id}/reindex")
    assert response.status_code == 409 and response.json()["detail"] == "remote_agents_disabled"
    assert db_session.query(AgentJob).filter_by(source_id=source.id).count() == 0


@pytest.mark.asyncio
async def test_dispatcher_missing_and_remote_inherits_agent_mode(db_session, approved_agent):
    dispatcher = ScanDispatcher(db_session, object())
    with pytest.raises(SourceNotFoundError):
        await dispatcher.dispatch("missing", "manual")
    source = Source(
        id="remote-source",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
    )
    db_session.add(source)
    db_session.commit()
    job = await dispatcher.dispatch(source.id, "schedule")
    assert job.processing_mode == "on_server"


@pytest.mark.asyncio
async def test_dispatcher_local_calls_indexer_with_full_flag(db_session, monkeypatch, tmp_path):
    source = Source(id="local-dispatch", name="Local", root_path=str(tmp_path))
    db_session.add(source)
    db_session.commit()
    stats = Mock()
    index = AsyncMock(return_value=stats)
    monkeypatch.setattr("app.services.scan_dispatcher.IndexingService.index_source", index)
    result = await ScanDispatcher(db_session, object()).dispatch(source.id, "manual", full=True)
    assert result is stats
    index.assert_called_once_with(source.id, full=True)


def test_remote_path_authorization_is_platform_aware_and_lexical(approved_agent):
    assert _remote_path_authorized(approved_agent, "/srv/docs/child")
    assert not _remote_path_authorized(approved_agent, "/srv/docs2")
    assert not _remote_path_authorized(approved_agent, "/srv/docs/../secret")
    windows = Agent(
        id="windows",
        name="W",
        platform="windows",
        version="1",
        protocol_version=1,
        allowed_roots=json.dumps([{"root_id": "docs", "path": "C:\\Data\\Docs"}]),
    )
    assert _remote_path_authorized(windows, "c:\\data\\docs\\Team")
    assert not _remote_path_authorized(windows, "C:\\Data\\Docs2")
    assert not _remote_path_authorized(windows, "D:\\Data\\Docs")
    assert not _remote_path_authorized(windows, " C:\\Data\\Docs ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_mode,default_mode,expected",
    [
        ("on_agent", "on_server", "on_agent"),
        ("on_server", "on_agent", "on_server"),
        (None, "on_agent", "on_agent"),
    ],
)
async def test_dispatcher_uses_override_or_agent_default_mode(
    db_session, approved_agent, source_mode, default_mode, expected
):
    approved_agent.default_processing_mode = default_mode
    source = Source(
        id=f"mode-{expected}-{source_mode}",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
        processing_mode=source_mode,
    )
    db_session.add(source)
    db_session.commit()
    job = await ScanDispatcher(db_session, object()).dispatch(source.id, "manual", full=True)
    assert job.processing_mode == expected and json.loads(job.payload) == {"full": True}


def test_remote_scheduler_coalesces_offline_jobs_without_local_lock(
    db_session, approved_agent, monkeypatch
):
    source = Source(
        id="scheduled-remote",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
        use_default_schedule=True,
    )
    source_id = source.id
    db_session.add(source)
    db_session.commit()
    svc = SchedulerService(db_session.get_bind())
    svc._session_factory = Mock(return_value=db_session)
    scheduler_job = Mock()
    scheduler_job.next_run_time = datetime.now(timezone.utc)
    svc.scheduler = Mock()
    svc.scheduler.get_job.return_value = scheduler_job
    monkeypatch.setattr(
        "app.services.scheduler.get_source_lock",
        lambda _: (_ for _ in ()).throw(AssertionError("remote used local lock")),
    )
    for _ in range(5):
        svc._run_indexing_job(source_id)
    jobs = db_session.query(AgentJob).filter_by(source_id=source_id).all()
    source = db_session.get(Source, source_id)
    assert len(jobs) == 1 and jobs[0].active_key == source_id
    assert source.last_scan_at is None and source.next_scan_at is not None


def test_offline_scheduled_job_is_claimed_after_heartbeat(client, db_session, approved_agent):
    source = Source(
        id="reconnect-remote",
        name="Remote",
        root_path="/srv/docs",
        location_type="agent",
        agent_id=approved_agent.id,
    )
    db_session.add(source)
    db_session.commit()
    import asyncio

    job = asyncio.run(ScanDispatcher(db_session, object()).dispatch(source.id, "schedule"))
    db_session.commit()
    headers = {"Authorization": "Bearer credential"}
    heartbeat = client.post(
        "/api/agent/v1/heartbeat",
        headers=headers,
        json={"protocol_version": 1, "agent_version": "1", "platform": "linux"},
    )
    assert heartbeat.status_code == 200 and heartbeat.json()["status"] == "online"
    claimed = client.post("/api/agent/v1/jobs/claim", headers=headers)
    assert claimed.status_code == 200
    assert claimed.json()["id"] == job.id and claimed.json()["processing_mode"] == "on_server"
