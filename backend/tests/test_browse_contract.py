import json
from datetime import datetime, timezone

import pytest
from onesearch_shared import PROTOCOL_VERSION

from app.models import Agent, AgentJob, AppSetting, Source
from app.services.agent_auth import hash_token
from app.services.agent_jobs import AgentJobService


@pytest.fixture
def approved_agent(db_session):
    agent = Agent(
        id="browse-agent", name="Browse", platform="linux", version="1",
        protocol_version=PROTOCOL_VERSION, token_hash=hash_token("credential"),
        allowed_roots=json.dumps([{"root_id": "docs", "path": "/srv/docs"}]),
        status="offline", approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add_all([agent, AppSetting(key="remote_agents_enabled", value="true")])
    db_session.commit()
    return agent


def test_browse_list_start_and_poll_persists_completed_result(client, db_session, approved_agent):
    approved_agent.status = "online"
    db_session.commit()
    start = client.post("/api/sources/browse", json={"agent_id": approved_agent.id, "root_id": "docs", "path": ""})
    assert start.status_code == 200
    job = db_session.get(AgentJob, start.json()["job_id"])
    assert json.loads(job.payload) == {"operation": "list", "root_id": "docs", "path": ""}

    job.status, job.active_key = "completed", None
    job.checkpoint = json.dumps({"browse_result": {"root_id": "docs", "path": "", "entries": [{"name": "team", "path": "team"}], "truncated": False}})
    db_session.commit()
    poll = client.get(f"/api/sources/browse/{job.id}")
    assert poll.status_code == 200
    assert poll.json()["entries"] == [{"name": "team", "path": "team"}]


def test_browse_completion_rejects_wrong_path_and_keeps_job_active(client, db_session, approved_agent):
    approved_agent.status = "online"
    job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "team")
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(approved_agent.id)
    db_session.commit()
    response = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers={"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": lease.lease_token},
        json={
            "job_id": job.id, "status": "succeeded",
            "browse_result": {
                "root_id": "docs", "path": "team",
                "entries": [{"name": "escape", "path": "other/escape"}], "truncated": False,
            },
        },
    )
    assert response.status_code == 409
    assert db_session.get(AgentJob, job.id).status == "claimed"


def test_browse_completion_persists_only_valid_success_and_failed_poll_has_no_entries(
    client, db_session, approved_agent
):
    approved_agent.status = "online"
    job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "team")
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(approved_agent.id)
    db_session.commit()
    headers = {"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": lease.lease_token}
    completion = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete", headers=headers,
        json={
            "job_id": job.id, "status": "succeeded",
            "browse_result": {
                "root_id": "docs", "path": "team",
                "entries": [{"name": "a", "path": "team/a"}, {"name": "z", "path": "team/z"}],
                "truncated": False,
            },
        },
    )
    assert completion.status_code == 200, completion.text
    stored = db_session.get(AgentJob, job.id)
    assert stored.status == "completed"
    assert json.loads(stored.checkpoint)["browse_result"]["entries"][0]["path"] == "team/a"

    failed = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "other")
    db_session.commit()
    failed_lease = AgentJobService(db_session).claim_next(approved_agent.id)
    db_session.commit()
    response = client.post(
        f"/api/agent/v1/jobs/{failed.id}/complete",
        headers={"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": failed_lease.lease_token},
        json={"job_id": failed.id, "status": "failed", "detail": "private host path"},
    )
    assert response.status_code == 200
    poll = client.get(f"/api/sources/browse/{failed.id}")
    assert poll.status_code == 200
    assert poll.json()["entries"] == [] and poll.json()["error"] == "Directory browse did not complete."


def test_browse_start_rejects_offline_and_unknown_root(client, db_session, approved_agent):
    offline = client.post(
        "/api/sources/browse", json={"agent_id": approved_agent.id, "root_id": "docs", "path": ""}
    )
    assert offline.status_code == 409
    approved_agent.status = "online"
    db_session.commit()
    unknown = client.post(
        "/api/sources/browse", json={"agent_id": approved_agent.id, "root_id": "unknown", "path": ""}
    )
    assert unknown.status_code == 422


def test_browse_poll_rejects_validation_and_hides_pending_entries(client, db_session, approved_agent):
    approved_agent.status = "online"
    validation = AgentJobService(db_session).enqueue_browse(approved_agent.id, "/srv/docs")
    listing = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "")
    db_session.commit()
    assert client.get(f"/api/sources/browse/{validation.id}").status_code == 404
    pending = client.get(f"/api/sources/browse/{listing.id}")
    assert pending.status_code == 200
    assert pending.json()["entries"] == [] and pending.json()["truncated"] is False


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "bad\u0000name", "path": "team/bad"},
        {"name": "bad", "path": "../bad"},
        {"name": "bad", "path": "/bad"},
    ],
)
def test_malicious_control_or_noncanonical_browse_wire_is_rejected_before_completion(
    client, db_session, approved_agent, entry
):
    approved_agent.status = "online"
    job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "team")
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(approved_agent.id)
    db_session.commit()
    response = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers={"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": lease.lease_token},
        json={"job_id": job.id, "status": "succeeded", "browse_result": {"root_id": "docs", "path": "team", "entries": [entry], "truncated": False}},
    )
    assert response.status_code == 422
    assert db_session.get(AgentJob, job.id).status == "claimed"


def test_browse_poll_handles_cancelled_without_entries_and_never_creates_source(
    client, db_session, approved_agent
):
    approved_agent.status = "online"
    job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "")
    job.status, job.active_key = "cancelled", None
    db_session.commit()
    response = client.get(f"/api/sources/browse/{job.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled" and response.json()["entries"] == []
    assert db_session.query(Source).count() == 0


def test_browse_completion_rejects_duplicate_and_over_cap_results_at_wire_boundary(
    client, db_session, approved_agent
):
    approved_agent.status = "online"
    for suffix, entries in (
        ("duplicate", [{"name": "a", "path": "duplicate/a"}, {"name": "a", "path": "duplicate/a"}]),
        ("cap", [{"name": f"d{i}", "path": f"cap/d{i}"} for i in range(501)]),
    ):
        job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", suffix)
        db_session.commit()
        lease = AgentJobService(db_session).claim_next(approved_agent.id)
        db_session.commit()
        response = client.post(
            f"/api/agent/v1/jobs/{job.id}/complete",
            headers={"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": lease.lease_token},
            json={"job_id": job.id, "status": "succeeded", "browse_result": {"root_id": "docs", "path": suffix, "entries": entries, "truncated": suffix == "cap"}},
        )
        assert response.status_code == 422


def test_browse_completion_rejects_unsorted_result_and_poll_preserves_truncated(
    client, db_session, approved_agent
):
    approved_agent.status = "online"
    job = AgentJobService(db_session).enqueue_browse_list(approved_agent.id, "docs", "")
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(approved_agent.id)
    db_session.commit()
    response = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers={"Authorization": "Bearer credential", "X-OneSearch-Lease-Token": lease.lease_token},
        json={"job_id": job.id, "status": "succeeded", "browse_result": {"root_id": "docs", "path": "", "entries": [{"name": "z", "path": "z"}, {"name": "a", "path": "a"}], "truncated": True}},
    )
    assert response.status_code == 409
    assert db_session.get(AgentJob, job.id).status == "claimed"

    job.status, job.active_key = "completed", None
    job.checkpoint = json.dumps({"browse_result": {"root_id": "docs", "path": "", "entries": [], "truncated": True}})
    db_session.commit()
    assert client.get(f"/api/sources/browse/{job.id}").json()["truncated"] is True
