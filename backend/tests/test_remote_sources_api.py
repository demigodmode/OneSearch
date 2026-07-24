"""Remote source and dispatcher boundaries."""

import json
from datetime import datetime, timezone

import pytest

from app.models import Agent, AppSetting, Source
from app.services.agent_auth import hash_token
from app.services.scan_dispatcher import ScanDispatcher, SourceNotFound


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


@pytest.mark.asyncio
async def test_dispatcher_missing_and_remote_inherits_agent_mode(db_session, approved_agent):
    dispatcher = ScanDispatcher(db_session, object())
    with pytest.raises(SourceNotFound):
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
