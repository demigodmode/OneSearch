import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from onesearch_shared import (
    REMOTE_MAX_BATCH_BYTES,
    REMOTE_MAX_BATCH_DOCUMENTS,
    REMOTE_MAX_ENTRIES_PER_DIRECTORY,
    REMOTE_MAX_SCAN_FILES,
    REMOTE_MAX_SNAPSHOT_BYTES,
    remote_path_hash,
)

from app.api import agent_protocol
from app.models import Agent, AgentJob, AppSetting, Source
from app.services.agent_auth import create_agent_token, hash_token
from app.services.agent_jobs import AgentJobService, JobConflict, JobNotFound


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def remote(db_session):
    agent = Agent(
        id="agent-1",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
        status="online",
        approved_at=now(),
    )
    source = Source(
        id="remote-1",
        name="Remote",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_agent",
    )
    db_session.add_all([agent, source])
    db_session.commit()
    return agent, source


def test_enqueue_coalesces_one_active_scan_per_source(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    first = service.enqueue_scan(source, full=True, reason="manual")
    second = service.enqueue_scan(source, full=False, reason="schedule")
    db_session.commit()
    assert first.id == second.id
    assert first.active_key == source.id
    payload = json.loads(first.payload)
    assert payload["full"] is True
    assert payload["root_path"] == source.root_path
    assert payload["known_files"] == {}
    assert payload["limits"] == {
        "max_snapshot_bytes": REMOTE_MAX_SNAPSHOT_BYTES,
        "max_batch_documents": REMOTE_MAX_BATCH_DOCUMENTS,
        "max_batch_bytes": REMOTE_MAX_BATCH_BYTES,
        "max_scan_files": REMOTE_MAX_SCAN_FILES,
        "max_entries_per_directory": REMOTE_MAX_ENTRIES_PER_DIRECTORY,
    }
    assert {
        "source_name",
        "unsupported_file_policy",
        "index_gps_metadata",
        "max_text_file_size_mb",
        "media_probe_max_size_mb",
    } <= set(payload["extraction"])


def test_claim_next_leases_extract_file_job_for_remote_transfer(db_session, remote):
    agent, source = remote
    job = AgentJob(
        id="extract-later",
        agent_id=agent.id,
        source_id=source.id,
        kind="extract_file",
        status="pending",
    )
    db_session.add(job)
    db_session.commit()

    lease = AgentJobService(db_session).claim_next(agent.id)

    assert lease is not None
    assert lease.id == job.id and lease.kind.value == "extract_file"
    assert lease.source_id == source.id and lease.lease_token
    db_session.refresh(job)
    assert job.status == "claimed" and job.attempts == 1
    assert job.lease_token_hash is not None and job.lease_expires_at is not None


def test_enqueue_snapshots_persisted_extraction_settings(db_session, remote):
    _agent, source = remote
    db_session.add_all(
        [
            AppSetting(key="unsupported_file_policy", value="skip"),
            AppSetting(key="index_gps_metadata", value="true"),
            AppSetting(key="media_probe_max_size_mb", value="0"),
        ]
    )
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    payload = json.loads(job.payload)
    assert payload["extraction"]["unsupported_file_policy"] == "skip"
    assert payload["extraction"]["index_gps_metadata"] is True
    assert payload["extraction"]["media_probe_max_size_mb"] == 0
    assert payload["limits"]["max_snapshot_bytes"] == REMOTE_MAX_SNAPSHOT_BYTES
    db_session.scalar(
        __import__("sqlalchemy")
        .select(AppSetting)
        .where(AppSetting.key == "unsupported_file_policy")
    ).value = "metadata_only"
    db_session.commit()
    assert json.loads(job.payload)["extraction"]["unsupported_file_policy"] == "skip"


def test_status_for_agent_limits_visibility_to_owner(db_session, remote):
    agent, source = remote
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    assert AgentJobService(db_session).status_for_agent(job.id, agent.id) is job
    with pytest.raises(JobNotFound):
        AgentJobService(db_session).status_for_agent(job.id, "other")
    with pytest.raises(JobNotFound):
        AgentJobService(db_session).status_for_agent("missing", agent.id)


def test_enqueue_includes_index_status_in_incremental_known_files(db_session, remote):
    from app.models import IndexedFile

    _agent, source = remote
    db_session.add(IndexedFile(source_id=source.id, path="retry.txt", status="failed"))
    db_session.commit()
    payload = json.loads(AgentJobService(db_session).enqueue_scan(source, full=False).payload)
    assert payload["known_files"]["retry.txt"]["status"] == "failed"


def test_enqueue_uses_legacy_datetime_when_exact_nanoseconds_are_absent(db_session, remote):
    from datetime import datetime, timezone

    from app.models import IndexedFile

    _agent, source = remote
    moment = datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc).replace(tzinfo=None)
    db_session.add(
        IndexedFile(source_id=source.id, path="legacy.txt", modified_at=moment, status="success")
    )
    db_session.commit()
    payload = json.loads(AgentJobService(db_session).enqueue_scan(source, full=False).payload)
    assert payload["known_files"]["legacy.txt"]["modified_at"] == 1704164645123456000


def test_claim_issues_hashed_lease_and_rejects_wrong_agent(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=10)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    db_session.refresh(job)
    assert lease.id == job.id and lease.source_id == source.id
    assert job.status == "claimed" and job.lease_token_hash != lease.lease_token
    with pytest.raises(JobNotFound):
        service.extend_lease("other", job.id, lease.lease_token)


def test_heartbeat_extends_lease_and_expired_lease_reclaims(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=10)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.extend_lease(agent.id, job.id, lease.lease_token, completed_items=2, total_items=3)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "running" and job.progress_current == 2
    job.lease_expires_at = now() - timedelta(seconds=1)
    db_session.commit()
    assert service.fail_expired_leases() == 1
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "pending" and job.lease_token_hash is None and job.active_key == source.id


def test_batches_are_idempotent_and_checksum_conflicts(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    payload = {"job_id": job.id, "batch_id": "batch-1", "documents": []}
    assert (
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch-1", payload).duplicate
        is False
    )
    db_session.commit()
    assert (
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch-1", payload).duplicate
        is True
    )
    with pytest.raises(JobConflict):
        service.accept_batch(
            agent.id, job.id, lease.lease_token, "batch-1", {**payload, "documents": [{"x": 1}]}
        )


def test_completion_and_cancellation_clear_active_key(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.complete_reconciled_scan(agent.id, job.id, lease.lease_token)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "completed" and job.active_key is None and job.lease_token_hash is None
    pending = service.enqueue_scan(source, full=True)
    db_session.commit()
    service.cancel(pending.id)
    db_session.commit()
    db_session.refresh(pending)
    assert pending.status == "cancelled" and pending.active_key is None


def test_cancelling_job_rejects_batches_until_agent_acknowledges(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    lease = service.claim_next(agent.id)
    db_session.commit()
    service.cancel(job.id)
    db_session.commit()
    with pytest.raises(JobConflict):
        service.accept_batch(agent.id, job.id, lease.lease_token, "batch", {"x": 1})
    service.complete(agent.id, job.id, lease.lease_token, "cancelled")
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "cancelled" and job.active_key is None


def test_expired_cancelling_job_is_finalized_and_frees_the_source(db_session, remote):
    agent, source = remote
    service = AgentJobService(db_session, lease_seconds=1)
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    service.claim_next(agent.id)
    db_session.commit()
    service.cancel(job.id)
    db_session.flush()
    job.lease_expires_at = now() - timedelta(seconds=1)
    db_session.commit()
    assert service.fail_expired_leases() == 1
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "cancelled" and job.active_key is None and job.lease_token_hash is None
    assert service.enqueue_scan(source, full=True).id != job.id


def test_agent_job_api_claim_progress_batch_completion_and_cancellation_ack(
    client, db_session, remote, monkeypatch
):
    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    service = AgentJobService(db_session)

    class FakeIngest:
        async def accept_batch(self, agent_id, job_id, token, batch):
            return AgentJobService(db_session).accept_batch(
                agent_id, job_id, token, batch.batch_id, batch.model_dump(mode="json")
            )

        async def reconcile_completion(self, agent_id, job_id, token):
            AgentJobService(db_session).complete_reconciled_scan(agent_id, job_id, token)

    monkeypatch.setattr(agent_protocol, "get_remote_ingest_service", lambda db: FakeIngest())
    job = service.enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    claimed = client.post("/api/agent/v1/jobs/claim", headers=headers)
    assert claimed.status_code == 200
    lease = claimed.json()
    lease_headers = {**headers, "X-OneSearch-Lease-Token": lease["lease_token"]}
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/heartbeat",
            headers=lease_headers,
            json={"job_id": job.id, "completed_items": 1, "total_items": 2},
        ).status_code
        == 200
    )
    batch = {"job_id": job.id, "batch_id": "batch-1", "documents": []}
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=batch
        ).json()["duplicate"]
        is False
    )
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=batch
        ).json()["duplicate"]
        is True
    )
    nonempty = {
        "job_id": job.id,
        "batch_id": "batch-strings",
        "documents": [
            {"source_id": source.id, "path": "string-id.txt", "content": "x", "modified_at": 1}
        ],
    }
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=nonempty
        ).status_code
        == 200
    )
    changed = {
        **batch,
        "documents": [{"source_id": source.id, "path": "x", "content": "x", "modified_at": 1}],
    }
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/batches", headers=lease_headers, json=changed
        ).status_code
        == 409
    )
    completed = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers=lease_headers,
        json={
            "job_id": job.id,
            "status": "succeeded",
            "reason": None,
            "detail": None,
            "checkpoint": None,
        },
    )
    assert completed.status_code == 200, completed.text
    cancelled = service.enqueue_scan(source, full=True)
    db_session.commit()
    cancel_lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()
    service.cancel(cancelled.id)
    db_session.commit()
    cancel_headers = {**headers, "X-OneSearch-Lease-Token": cancel_lease["lease_token"]}
    ack = client.post(f"/api/agent/v1/jobs/{cancelled.id}/cancel-ack", headers=cancel_headers)
    assert ack.status_code == 200


def test_failed_completion_api_accepts_reason_and_persists_detail(client, db_session, remote):
    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()
    response = client.post(
        f"/api/agent/v1/jobs/{job.id}/complete",
        headers={**headers, "X-OneSearch-Lease-Token": lease["lease_token"]},
        json={"job_id": job.id, "status": "failed", "reason": "internal_error", "detail": "boom"},
    )
    assert response.status_code == 200
    assert db_session.get(type(job), job.id).status == "failed"
    assert db_session.get(type(job), job.id).error == "boom"


def test_agent_job_api_rejects_bad_agent_lease_and_disabled_feature(
    client, db_session, remote, monkeypatch
):
    from app.api import agent_protocol

    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    lease = client.post("/api/agent/v1/jobs/claim", headers=headers).json()["lease_token"]
    assert (
        client.post(
            f"/api/agent/v1/jobs/{job.id}/heartbeat",
            headers=headers,
            json={"job_id": job.id, "completed_items": 1},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/agent/v1/jobs/missing/heartbeat",
            headers={**headers, "X-OneSearch-Lease-Token": lease},
            json={"job_id": "missing", "completed_items": 1},
        ).status_code
        == 404
    )
    db_session.get(AppSetting, "remote_agents_enabled").value = "false"
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 409
    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 1)


def test_claim_without_work_returns_bounded_204_and_closes_poll_session(
    client, db_session, remote, monkeypatch
):
    from app.api import agent_protocol

    agent, _ = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    closed = []
    original = agent_protocol.make_claim_session

    def tracked(request_db):
        session = original(request_db)
        close = session.close

        def close_tracked():
            closed.append(True)
            close()

        session.close = close_tracked
        return session

    monkeypatch.setattr(agent_protocol, "make_claim_session", tracked)
    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 1)
    response = client.post("/api/agent/v1/jobs/claim", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    assert closed and all(closed)


@pytest.mark.asyncio
async def test_claim_poll_waits_exactly_the_configured_deadline(monkeypatch, db_session, remote):
    from app.api import agent_protocol

    agent, _ = remote
    agent.status = "online"
    agent.approved_at = now()
    timeline = [0.0]

    async def advance(seconds):
        timeline[0] += seconds

    class EmptySession:
        def close(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(agent_protocol, "CLAIM_TIMEOUT_SECONDS", 25)
    monkeypatch.setattr(agent_protocol, "CLAIM_POLL_SECONDS", 1)
    monkeypatch.setattr(agent_protocol, "claim_clock", lambda: timeline[0])
    monkeypatch.setattr(agent_protocol, "claim_sleep", advance)
    monkeypatch.setattr(agent_protocol, "make_claim_session", lambda _: EmptySession())
    monkeypatch.setattr(
        agent_protocol,
        "AgentJobService",
        lambda _: type("S", (), {"claim_next": lambda *_: None})(),
    )
    response = await agent_protocol.claim_job(agent, db_session)
    assert response.status_code == 204
    assert timeline[0] == 25


def test_job_endpoints_reject_user_pending_disabled_and_revoked_agents(
    client, db_session, remote, auth_headers
):
    agent, _ = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    agent.status = "pending"
    agent.approved_at = None
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=auth_headers).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 403
    agent.status = "disabled"
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 403
    agent.status = "revoked"
    agent.token_hash = None
    db_session.commit()
    assert client.post("/api/agent/v1/jobs/claim", headers=headers).status_code == 401


def test_other_agent_cannot_upload_to_owned_extract_job(
    client, db_session, remote, tmp_path, monkeypatch
):
    agent_a, source = remote
    source.processing_mode = "on_server"
    token_a, token_b = create_agent_token(), create_agent_token()
    agent_a.token_hash = hash_token(token_a)
    agent_b = Agent(
        id="agent-b",
        name="B",
        platform="windows",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
        status="online",
        approved_at=now(),
    )
    agent_b.token_hash = hash_token(token_b)
    db_session.add_all([agent_b, AppSetting(key="remote_agents_enabled", value="true")])
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent_a.id)
    db_session.commit()
    assert lease.id == child.id
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    monkeypatch.setattr(agent_protocol, "extract_uploads", registry)
    response = client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=0",
        content=b"x",
        headers={
            "Authorization": f"Bearer {token_b}",
            "X-OneSearch-Lease-Token": lease.lease_token,
        },
    )
    assert response.status_code in {401, 403, 404}
    assert not registry._sessions
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("changed_paths", "expected_paths"),
    [(None, ["a.txt", "b.txt"]), ([], []), (["b.txt"], ["b.txt"])],
)
def test_on_server_manifest_selects_changed_files_only(
    client, db_session, remote, changed_paths, expected_paths
):
    agent, source = remote
    source.processing_mode = "on_server"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    files = [
        {"path": path, "path_hash": remote_path_hash(path), "size_bytes": 1, "modified_at": 1}
        for path in ["a.txt", "b.txt"]
    ]
    manifest = {"job_id": parent.id, "source_id": source.id, "files": files, "complete": True}
    if changed_paths is not None:
        manifest["changed_paths"] = changed_paths
    response = client.post(
        f"/api/agent/v1/jobs/{parent.id}/manifest",
        headers={"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token},
        json=manifest,
    )
    assert response.status_code == 200, response.text
    retry = client.post(
        f"/api/agent/v1/jobs/{parent.id}/manifest",
        headers={"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token},
        json=manifest,
    )
    assert retry.status_code == 200, retry.text
    children = db_session.query(AgentJob).filter_by(kind="extract_file").all()
    assert [json.loads(child.payload)["path"] for child in children] == expected_paths
    assert len(json.loads(parent.checkpoint)["remote_manifest"]["files"]) == 2


def test_extract_final_parent_rejection_cleans_upload_session(
    client, db_session, remote, tmp_path, monkeypatch
):
    agent, source = remote
    source.processing_mode = "on_server"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    monkeypatch.setattr(agent_protocol, "extract_uploads", registry)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    assert (
        client.put(
            f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=0", content=b"x", headers=headers
        ).status_code
        == 200
    )
    child.payload = child.payload.replace(parent.id, "missing-parent")
    db_session.commit()
    response = client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=1&complete=true&stream_checksum={hashlib.sha256(b'x').hexdigest()}",
        headers=headers,
    )
    assert response.status_code == 409
    assert not registry.has(child.id) and list(tmp_path.iterdir()) == []


def test_invalid_later_extract_chunk_cleans_partial_upload(
    client, db_session, remote, tmp_path, monkeypatch
):
    agent, source = remote
    source.processing_mode = "on_server"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 2, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    monkeypatch.setattr(agent_protocol, "extract_uploads", registry)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    assert client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=0&checksum={hashlib.sha256(b'x').hexdigest()}", content=b"x", headers=headers
    ).status_code == 200
    malformed_headers = {**headers, "Content-Length": "not-a-length"}
    response = client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=1",
        content=b"x",
        headers=malformed_headers,
    )
    assert response.status_code == 409
    assert not registry.has(child.id) and list(tmp_path.iterdir()) == []


def test_failed_extract_completion_cleans_partial_upload(client, db_session, remote, tmp_path, monkeypatch):
    agent, source = remote
    source.processing_mode = "on_server"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    monkeypatch.setattr(agent_protocol, "extract_uploads", registry)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    assert client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=0", content=b"x", headers=headers
    ).status_code == 200
    response = client.post(
        f"/api/agent/v1/jobs/{child.id}/complete",
        headers=headers,
        json={"job_id": child.id, "status": "failed", "reason": "internal_error", "detail": "failed"},
    )
    assert response.status_code == 200
    assert not registry.has(child.id) and list(tmp_path.iterdir()) == []


def test_extract_cancellation_acknowledgement_cleans_partial_upload(
    client, db_session, remote, tmp_path, monkeypatch
):
    agent, source = remote
    source.processing_mode = "on_server"
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    parent = AgentJobService(db_session).enqueue_scan(source, full=True)
    child = AgentJobService(db_session).enqueue_extract_files(
        parent, [{"path": "a.txt", "size_bytes": 1, "modified_at": 1, "content_hash": None}]
    )[0]
    parent.status, parent.lease_token_hash, parent.lease_expires_at = "running", None, None
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    from app.services.remote_files import ExtractUploadRegistry

    registry = ExtractUploadRegistry(tmp_path)
    monkeypatch.setattr(agent_protocol, "extract_uploads", registry)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    assert client.put(
        f"/api/agent/v1/jobs/{child.id}/file-chunks?sequence=0", content=b"x", headers=headers
    ).status_code == 200
    AgentJobService(db_session).cancel(child.id)
    db_session.commit()
    response = client.post(f"/api/agent/v1/jobs/{child.id}/cancel-ack", headers=headers)
    assert response.status_code == 200
    assert not registry.has(child.id) and list(tmp_path.iterdir()) == []


def test_stream_final_checksum_requires_registered_consumer_and_durable_completion(
    client, db_session, remote
):
    from app.models import AgentJob
    from app.services.remote_files import remote_streams

    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    job = AgentJob(
        id="stream-red",
        agent_id=agent.id,
        source_id=source.id,
        kind="stream_file",
        status="pending",
        processing_mode="on_server",
        active_key="stream-red",
        payload="{}",
        checkpoint="{}",
    )
    db_session.add(job)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    queue = remote_streams.open(job.id, expected_size=1)
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    try:
        assert (
            client.put(
                f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=0&checksum={hashlib.sha256(b'x').hexdigest()}", content=b"x", headers=headers
            ).status_code
            == 200
        )
        final = client.put(
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=1&complete=true&stream_checksum={hashlib.sha256(b'x').hexdigest()}",
            headers=headers,
        )
        assert final.status_code == 200
        assert __import__("asyncio").run(queue.get()) == b"x"
        assert __import__("asyncio").run(queue.get()) is None
        db_session.refresh(job)
        assert job.status == "completed"
    finally:
        __import__("asyncio").run(remote_streams.close(job.id))


def test_stream_chunk_without_registered_consumer_is_structured_conflict(
    client, db_session, remote
):
    from app.models import AgentJob

    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    job = AgentJob(
        id="stream-no-queue",
        agent_id=agent.id,
        source_id=source.id,
        kind="stream_file",
        status="pending",
        processing_mode="on_server",
        active_key="stream-no-queue",
        payload="{}",
        checkpoint="{}",
    )
    db_session.add(job)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    response = client.put(
        f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=0&checksum={hashlib.sha256(b'x').hexdigest()}",
        content=b"x",
        headers={"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token},
    )
    assert (
        response.status_code == 409 and response.json()["detail"]["code"] == "remote_stream_timeout"
    )
    db_session.refresh(job)
    assert job.status == "claimed" and job.active_key == "stream-no-queue"


@pytest.mark.parametrize(
    "query,body",
    [
        ("sequence=1", b"x"),
        ("sequence=0&checksum=" + "0" * 64, b"x"),
        ("sequence=0&complete=true&stream_checksum=" + "0" * 64, b""),
    ],
)
def test_stream_invalid_transfer_is_changed_conflict(client, db_session, remote, query, body):
    from app.models import AgentJob
    from app.services.remote_files import remote_streams

    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    job = AgentJob(
        id=f"stream-invalid-{query[:8]}",
        agent_id=agent.id,
        source_id=source.id,
        kind="stream_file",
        status="pending",
        processing_mode="on_server",
        active_key=f"stream-invalid-{query[:8]}",
        payload="{}",
        checkpoint="{}",
    )
    db_session.add(job)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    remote_streams.open(job.id, expected_size=1)
    try:
        response = client.put(
            f"/api/agent/v1/jobs/{job.id}/file-chunks?{query}",
            content=body,
            headers={
                "Authorization": f"Bearer {token}",
                "X-OneSearch-Lease-Token": lease.lease_token,
            },
        )
        assert (
            response.status_code == 409
            and response.json()["detail"]["code"] == "remote_file_changed"
        )
        db_session.refresh(job)
        assert job.status == "claimed"
    finally:
        asyncio.run(remote_streams.close(job.id))


def test_stream_size_mismatches_reject_before_completion_or_eof(client, db_session, remote):
    from app.services.remote_files import remote_streams

    agent, job, token, lease = _leased_stream_job(db_session, remote, job_id="stream-size-under")
    headers = {"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token}
    queue = remote_streams.open(job.id, expected_size=2)
    try:
        assert client.put(
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=0&checksum={hashlib.sha256(b'x').hexdigest()}",
            content=b"x",
            headers=headers,
        ).status_code == 200
        response = client.put(
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=1&complete=true&stream_checksum={hashlib.sha256(b'x').hexdigest()}",
            headers=headers,
        )
        assert response.status_code == 409 and response.json()["detail"]["code"] == "remote_file_changed"
        db_session.refresh(job)
        assert job.status == "claimed" and not queue._finished
    finally:
        asyncio.run(remote_streams.close(job.id))

    agent, job, token, lease = _leased_stream_job(db_session, remote, job_id="stream-size-over")
    queue = remote_streams.open(job.id, expected_size=1)
    try:
        response = client.put(
            f"/api/agent/v1/jobs/{job.id}/file-chunks?sequence=0&checksum={hashlib.sha256(b'ab').hexdigest()}",
            content=b"ab",
            headers={"Authorization": f"Bearer {token}", "X-OneSearch-Lease-Token": lease.lease_token},
        )
        assert response.status_code == 409 and response.json()["detail"]["code"] == "remote_file_changed"
        db_session.refresh(job)
        assert job.status == "claimed" and queue._items.empty() and not queue._finished
    finally:
        asyncio.run(remote_streams.close(job.id))


def _leased_stream_job(db_session, remote, *, job_id):
    agent, source = remote
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    if db_session.get(AppSetting, "remote_agents_enabled") is None:
        db_session.add(AppSetting(key="remote_agents_enabled", value="true"))
    job = AgentJob(
        id=job_id,
        agent_id=agent.id,
        source_id=source.id,
        kind="stream_file",
        status="pending",
        processing_mode="on_server",
        active_key=job_id,
        payload="{}",
        checkpoint="{}",
    )
    db_session.add(job)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    return agent, job, token, lease


def _completion_while_stream_consumer_waits(client, job, token, lease, queue, payload):
    async def complete_and_receive():
        waiting_consumer = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        response = client.post(
            f"/api/agent/v1/jobs/{job.id}/complete",
            headers={
                "Authorization": f"Bearer {token}",
                "X-OneSearch-Lease-Token": lease.lease_token,
            },
            json=payload,
        )
        try:
            return response, await asyncio.wait_for(waiting_consumer, timeout=0.1)
        except BaseException as error:
            return response, error

    return asyncio.run(complete_and_receive())


@pytest.mark.parametrize(
    ("reason", "detail", "expected_error"),
    [
        ("not_found", "remote_file_missing", "RemoteFileMissing"),
        ("invalid_request", "remote_file_changed", "RemoteFileChanged"),
    ],
)
def test_stream_failed_completion_signals_trusted_terminal_error(
    client, db_session, remote, reason, detail, expected_error
):
    from app.services import remote_files

    _agent, job, token, lease = _leased_stream_job(
        db_session, remote, job_id=f"stream-failure-{reason}"
    )
    queue = remote_files.remote_streams.open(job.id, expected_size=1)
    try:
        response, result = _completion_while_stream_consumer_waits(
            client,
            job,
            token,
            lease,
            queue,
            {"job_id": job.id, "status": "failed", "reason": reason, "detail": detail},
        )
        assert response.status_code == 200
        assert isinstance(result, getattr(remote_files, expected_error))
        assert remote_files.remote_streams.get(job.id) is None
        db_session.refresh(job)
        assert job.status == "failed" and job.error == detail
    finally:
        asyncio.run(remote_files.remote_streams.close(job.id))


@pytest.mark.parametrize(
    ("reason", "detail"),
    [
        ("not_found", r"\\private-host\secrets\report.pdf"),
        ("invalid_request", "wrong-wire-code"),
        ("extraction_failed", "private-host extraction trace"),
    ],
)
def test_stream_failed_completion_hides_untrusted_terminal_detail(
    client, db_session, remote, reason, detail
):
    from app.services import remote_files

    _agent, job, token, lease = _leased_stream_job(
        db_session, remote, job_id=f"stream-untrusted-{reason}"
    )
    queue = remote_files.remote_streams.open(job.id, expected_size=1)
    try:
        response, result = _completion_while_stream_consumer_waits(
            client,
            job,
            token,
            lease,
            queue,
            {"job_id": job.id, "status": "failed", "reason": reason, "detail": detail},
        )
        assert response.status_code == 200
        assert isinstance(result, remote_files.RemoteStreamTimeout)
        assert detail not in response.text and detail not in str(result)
        assert remote_files.remote_streams.get(job.id) is None
        db_session.refresh(job)
        assert job.error == "remote_stream_failed"
    finally:
        asyncio.run(remote_files.remote_streams.close(job.id))


def test_stream_cancel_acknowledgment_closes_waiting_consumer(client, db_session, remote):
    from app.services import remote_files

    agent, job, token, lease = _leased_stream_job(db_session, remote, job_id="stream-cancel")
    queue = remote_files.remote_streams.open(job.id, expected_size=1)
    AgentJobService(db_session).cancel(job.id)
    db_session.commit()
    try:

        async def acknowledge_and_receive():
            waiting_consumer = asyncio.create_task(queue.get())
            await asyncio.sleep(0)
            response = client.post(
                f"/api/agent/v1/jobs/{job.id}/cancel-ack",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-OneSearch-Lease-Token": lease.lease_token,
                },
            )
            try:
                return response, await asyncio.wait_for(waiting_consumer, timeout=0.1)
            except BaseException as error:
                return response, error

        response, result = asyncio.run(acknowledge_and_receive())
        assert response.status_code == 200
        assert isinstance(result, remote_files.RemoteStreamTimeout)
        assert remote_files.remote_streams.get(job.id) is None
        db_session.refresh(job)
        assert job.status == "cancelled" and job.active_key is None
    finally:
        asyncio.run(remote_files.remote_streams.close(job.id))


def test_stream_cancel_acknowledgment_unblocks_backpressured_producer(client, db_session, remote):
    from app.services import remote_files

    agent, job, token, lease = _leased_stream_job(
        db_session, remote, job_id="stream-cancel-producer"
    )
    queue = remote_files.remote_streams.open(job.id, expected_size=2, max_bytes=1)
    AgentJobService(db_session).cancel(job.id)
    db_session.commit()
    try:

        async def acknowledge_and_produce():
            await queue.put(0, b"x", hashlib.sha256(b"x").hexdigest())
            blocked_producer = asyncio.create_task(
                queue.put(1, b"y", hashlib.sha256(b"y").hexdigest())
            )
            await asyncio.sleep(0)
            response = client.post(
                f"/api/agent/v1/jobs/{job.id}/cancel-ack",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-OneSearch-Lease-Token": lease.lease_token,
                },
            )
            try:
                return response, await asyncio.wait_for(blocked_producer, timeout=0.1)
            except BaseException as error:
                return response, error

        response, result = asyncio.run(acknowledge_and_produce())
        assert response.status_code == 200
        assert isinstance(result, remote_files.RemoteStreamTimeout)
        assert remote_files.remote_streams.get(job.id) is None
        db_session.refresh(job)
        assert job.status == "cancelled" and job.active_key is None
    finally:
        asyncio.run(remote_files.remote_streams.close(job.id))
