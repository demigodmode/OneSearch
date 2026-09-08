import hashlib
import json
from datetime import datetime, timezone

import pytest
from onesearch_shared import (
    ScanCheckpoint,
    ScanFile,
    ScanManifestPage,
    ScanManifestPagePayload,
    ScanPageOutcome,
    ScanPageOutcomePayload,
    ScanPathOutcome,
    canonical_wire_bytes,
    remote_path_hash,
)
from sqlalchemy import select

from app.models import (
    Agent,
    AgentScanEntry,
    AgentScanPage,
    AppSetting,
    IndexedFile,
    Source,
)
from app.services.agent_auth import create_agent_token, hash_token
from app.services.agent_jobs import AgentJobService, JobConflict, JobLeaseError
from app.services.remote_ingest import RemoteIngestService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _file(path, *, size=1, modified_at=1, content_hash=None):
    return ScanFile(
        path=path,
        path_hash=remote_path_hash(path),
        size_bytes=size,
        modified_at=modified_at,
        content_hash=content_hash,
    )


def _page(job, files, *, sequence=0, scanned_count=None, final=False, cursor=None):
    payload = ScanManifestPagePayload(
        job_id=job.id,
        source_id=job.source_id,
        sequence=sequence,
        files=files,
        checkpoint=ScanCheckpoint(
            cursor=cursor or f"page:{sequence}",
            scanned_count=len(files) if scanned_count is None else scanned_count,
        ),
        final=final,
    )
    return ScanManifestPage(
        checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(),
        page=payload,
    )


def _outcome(page, results):
    payload = ScanPageOutcomePayload(
        job_id=page.page.job_id,
        source_id=page.page.source_id,
        sequence=page.page.sequence,
        page_checksum=page.checksum,
        results=results,
    )
    return ScanPageOutcome(
        checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(),
        outcome=payload,
    )


@pytest.fixture
def paged_job(db_session):
    agent = Agent(
        id="page-agent",
        name="Page agent",
        platform="linux",
        version="1.4.0",
        protocol_version=3,
        allowed_roots='[{"root_id":"data","path":"/data"}]',
        status="online",
        approved_at=_now(),
    )
    source = Source(
        id="page-source",
        name="Paged source",
        root_path="/data",
        location_type="agent",
        agent_id=agent.id,
        processing_mode="on_agent",
    )
    db_session.add_all([agent, source])
    db_session.flush()
    db_session.add_all(
        [
            IndexedFile(
                source_id=source.id,
                path="unchanged.txt",
                size_bytes=1,
                modified_at_ns=10,
                status="success",
            ),
            IndexedFile(
                source_id=source.id,
                path="changed.txt",
                size_bytes=1,
                modified_at_ns=10,
                status="success",
            ),
            IndexedFile(
                source_id=source.id,
                path="retry.txt",
                size_bytes=1,
                modified_at_ns=10,
                status="failed",
            ),
            IndexedFile(source_id=source.id, path="not-present.txt", status="success"),
        ]
    )
    db_session.commit()
    job = AgentJobService(db_session).enqueue_scan(source, full=False)
    db_session.commit()
    lease = AgentJobService(db_session).claim_next(agent.id)
    db_session.commit()
    return db_session, agent, source, job, lease


def test_manifest_page_persists_stable_change_decisions_without_deleting(paged_job):
    db, agent, source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    page = _page(
        job,
        [
            _file("unchanged.txt", modified_at=10),
            _file("changed.txt", size=2, modified_at=10),
            _file("retry.txt", modified_at=10),
            _file("new.txt", modified_at=10),
        ],
        scanned_count=4,
        final=True,
    )

    first = service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)
    duplicate = service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert (
        first.changed_paths
        == duplicate.changed_paths
        == [
            "changed.txt",
            "new.txt",
            "retry.txt",
        ]
    )
    assert first.accepted_count == 4
    persisted = list(
        db.scalars(
            select(AgentScanEntry)
            .where(AgentScanEntry.job_id == job.id)
            .order_by(AgentScanEntry.path)
        )
    )
    assert [(item.path, item.needs_processing) for item in persisted] == [
        ("changed.txt", True),
        ("new.txt", True),
        ("retry.txt", True),
        ("unchanged.txt", False),
    ]
    assert db.scalar(
        select(IndexedFile).where(
            IndexedFile.source_id == source.id, IndexedFile.path == "not-present.txt"
        )
    )

    conflict = _page(job, [_file("other.txt")], scanned_count=1, final=True)
    with pytest.raises(JobConflict):
        service.accept_manifest_page(agent.id, job.id, lease.lease_token, conflict)


def test_manifest_page_uses_content_hash_when_both_sides_provide_one(paged_job):
    db, agent, _source, job, lease = paged_job
    stored = db.scalar(select(IndexedFile).where(IndexedFile.path == "unchanged.txt"))
    stored.hash = "sha256:stored"
    db.flush()

    ack = RemoteIngestService(db, object()).accept_manifest_page(
        agent.id,
        job.id,
        lease.lease_token,
        _page(
            job,
            [
                _file(
                    "unchanged.txt",
                    modified_at=10,
                    content_hash="sha256:different",
                )
            ],
            final=True,
        ),
    )

    assert ack.changed_paths == ["unchanged.txt"]


def test_manifest_pages_require_contiguous_monotonic_single_final_traversal(paged_job):
    db, agent, _source, job, lease = paged_job
    service = RemoteIngestService(db, object())

    with pytest.raises(JobConflict):
        service.accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(job, [_file("late.txt")], sequence=1, scanned_count=1),
        )

    first = _page(job, [_file("a.txt")], scanned_count=1)
    service.accept_manifest_page(agent.id, job.id, lease.lease_token, first)
    with pytest.raises(JobConflict):
        service.accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(job, [_file("gap.txt")], sequence=2, scanned_count=2),
        )
    with pytest.raises(JobConflict):
        service.accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(job, [_file("stalled.txt")], sequence=1, scanned_count=1),
        )

    final = _page(job, [], sequence=1, scanned_count=1, final=True, cursor="complete")
    accepted = service.accept_manifest_page(agent.id, job.id, lease.lease_token, final)
    duplicate = service.accept_manifest_page(agent.id, job.id, lease.lease_token, final)
    assert accepted.accepted_count == 0 and accepted.changed_paths == []
    assert accepted.duplicate is False and duplicate.duplicate is True
    with pytest.raises(JobConflict):
        service.accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(job, [_file("after.txt")], sequence=2, scanned_count=2),
        )


def test_manifest_pages_reject_paths_repeated_across_pages(paged_job):
    db, agent, _source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    service.accept_manifest_page(
        agent.id, job.id, lease.lease_token, _page(job, [_file("same.txt")], scanned_count=1)
    )

    with pytest.raises(JobConflict):
        service.accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(
                job,
                [_file("same.txt")],
                sequence=1,
                scanned_count=2,
                final=True,
            ),
        )


def test_manifest_page_rejects_wrong_lease_source_job_shape_and_legacy_payload(paged_job):
    db, agent, _source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    page = _page(job, [_file("a.txt")], scanned_count=1, final=True)

    with pytest.raises(JobLeaseError):
        service.accept_manifest_page(agent.id, job.id, "wrong", page)

    wrong_source_payload = page.page.model_copy(update={"source_id": "other"})
    wrong_source = ScanManifestPage(
        checksum=hashlib.sha256(canonical_wire_bytes(wrong_source_payload)).hexdigest(),
        page=wrong_source_payload,
    )
    with pytest.raises(JobConflict):
        service.accept_manifest_page(agent.id, job.id, lease.lease_token, wrong_source)

    job.payload = json.dumps({"full": False})
    db.flush()
    with pytest.raises(JobConflict):
        service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)


@pytest.mark.parametrize(
    "payload",
    [json.dumps([]), json.dumps("invalid"), json.dumps({"protocol_version": "3"})],
)
def test_manifest_page_rejects_malformed_paged_job_payload(paged_job, payload):
    db, agent, _source, job, lease = paged_job
    job.payload = payload
    db.flush()

    with pytest.raises(JobConflict):
        RemoteIngestService(db, object()).accept_manifest_page(
            agent.id,
            job.id,
            lease.lease_token,
            _page(job, [_file("a.txt")], final=True),
        )


def test_on_agent_page_outcome_settles_exact_changed_paths_idempotently(paged_job):
    db, agent, source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    page = _page(
        job,
        [_file("new.txt", size=2, modified_at=20), _file("unchanged.txt", modified_at=10)],
        final=True,
    )
    service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)
    db.add(
        IndexedFile(
            source_id=source.id,
            path="new.txt",
            size_bytes=2,
            modified_at_ns=20,
            status="success",
        )
    )
    db.flush()
    outcome = _outcome(page, [ScanPathOutcome(path="new.txt", status="indexed")])

    first = service.accept_page_outcome(agent.id, job.id, lease.lease_token, outcome)
    duplicate = service.accept_page_outcome(agent.id, job.id, lease.lease_token, outcome)
    settled_page_retry = service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)

    assert first.duplicate is False and duplicate.duplicate is True
    assert settled_page_retry.duplicate is True
    assert settled_page_retry.changed_paths == ["new.txt"]
    assert first.settled_count == duplicate.settled_count == 1
    staged_page = db.scalar(select(AgentScanPage).where(AgentScanPage.job_id == job.id))
    staged_entry = db.scalar(select(AgentScanEntry).where(AgentScanEntry.job_id == job.id))
    assert staged_page.outcome_checksum == outcome.checksum
    assert staged_page.settled_at is not None
    assert staged_entry.outcome_status == "indexed" and staged_entry.failure_error is None
    assert json.loads(job.checkpoint) == {
        "scan_page": {
            "cursor": page.page.checkpoint.cursor,
            "final": True,
            "scanned_count": page.page.checkpoint.scanned_count,
            "sequence": 0,
        },
        "version": 2,
    }

    changed = _outcome(
        page, [ScanPathOutcome(path="new.txt", status="failed", error="later failure")]
    )
    with pytest.raises(JobConflict):
        service.accept_page_outcome(agent.id, job.id, lease.lease_token, changed)


def test_failed_and_skipped_outcomes_only_update_staging_rows(paged_job):
    db, agent, source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    page = _page(
        job,
        [_file("changed.txt", size=2, modified_at=10), _file("new.txt")],
        final=True,
    )
    service.accept_manifest_page(agent.id, job.id, lease.lease_token, page)

    service.accept_page_outcome(
        agent.id,
        job.id,
        lease.lease_token,
        _outcome(
            page,
            [
                ScanPathOutcome(path="changed.txt", status="failed", error="cannot read"),
                ScanPathOutcome(path="new.txt", status="skipped"),
            ],
        ),
    )

    changed = db.scalar(
        select(IndexedFile).where(
            IndexedFile.source_id == source.id, IndexedFile.path == "changed.txt"
        )
    )
    assert changed.status == "success" and changed.error_message is None
    assert (
        db.scalar(
            select(IndexedFile).where(
                IndexedFile.source_id == source.id, IndexedFile.path == "new.txt"
            )
        )
        is None
    )
    staged = list(
        db.scalars(
            select(AgentScanEntry)
            .where(AgentScanEntry.job_id == job.id)
            .order_by(AgentScanEntry.path)
        )
    )
    assert [(entry.path, entry.outcome_status, entry.failure_error) for entry in staged] == [
        ("changed.txt", "failed", "cannot read"),
        ("new.txt", "skipped", None),
    ]


def test_on_server_scan_accepts_pages_but_rejects_agent_outcomes(paged_job):
    db, agent, source, job, lease = paged_job
    source.processing_mode = job.processing_mode = "on_server"
    db.flush()
    service = RemoteIngestService(db, object())
    page = _page(job, [_file("new.txt")], final=True)

    assert service.accept_manifest_page(
        agent.id, job.id, lease.lease_token, page
    ).changed_paths == ["new.txt"]
    with pytest.raises(JobConflict):
        service.accept_page_outcome(
            agent.id,
            job.id,
            lease.lease_token,
            _outcome(page, [ScanPathOutcome(path="new.txt", status="skipped")]),
        )


def test_page_outcome_rejects_partial_unchanged_and_out_of_order_results(paged_job):
    db, agent, _source, job, lease = paged_job
    service = RemoteIngestService(db, object())
    first = _page(
        job,
        [_file("changed.txt", size=2, modified_at=10), _file("unchanged.txt", modified_at=10)],
        scanned_count=2,
    )
    second = _page(
        job,
        [_file("new.txt")],
        sequence=1,
        scanned_count=3,
        final=True,
    )
    service.accept_manifest_page(agent.id, job.id, lease.lease_token, first)
    service.accept_manifest_page(agent.id, job.id, lease.lease_token, second)

    with pytest.raises(JobConflict):
        service.accept_page_outcome(
            agent.id,
            job.id,
            lease.lease_token,
            _outcome(second, [ScanPathOutcome(path="new.txt", status="failed", error="x")]),
        )
    with pytest.raises(JobConflict):
        service.accept_page_outcome(agent.id, job.id, lease.lease_token, _outcome(first, []))
    with pytest.raises(JobConflict):
        service.accept_page_outcome(
            agent.id,
            job.id,
            lease.lease_token,
            _outcome(
                first,
                [
                    ScanPathOutcome(path="changed.txt", status="failed", error="x"),
                    ScanPathOutcome(path="unchanged.txt", status="skipped"),
                ],
            ),
        )


def test_manifest_page_api_authenticates_leases_and_sanitizes_conflicts(client, paged_job):
    db, agent, _source, job, lease = paged_job
    token = create_agent_token()
    agent.token_hash = hash_token(token)
    db.add(AppSetting(key="remote_agents_enabled", value="true"))
    db.commit()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-OneSearch-Lease-Token": lease.lease_token,
    }
    page = _page(job, [_file("new.txt")], final=True)
    url = f"/api/agent/v1/jobs/{job.id}/manifest-pages"

    accepted = client.post(url, headers=headers, json=page.model_dump(mode="json"))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["changed_paths"] == ["new.txt"]
    assert (
        client.post(url, headers=headers, json=page.model_dump(mode="json")).json()["duplicate"]
        is True
    )

    conflict = _page(job, [_file("secret/path.txt")], final=True)
    rejected = client.post(url, headers=headers, json=conflict.model_dump(mode="json"))
    assert rejected.status_code == 409
    assert rejected.json() == {"detail": "Job state conflict"}
    assert "secret/path.txt" not in rejected.text
    missing_lease = client.post(
        url, headers={"Authorization": f"Bearer {token}"}, json=page.model_dump(mode="json")
    )
    assert missing_lease.status_code == 401
    assert missing_lease.json() == {"detail": "Invalid or expired job lease"}

    outcome = _outcome(
        page, [ScanPathOutcome(path="new.txt", status="failed", error="private detail")]
    )
    outcome_url = f"/api/agent/v1/jobs/{job.id}/page-outcomes"
    settled = client.post(outcome_url, headers=headers, json=outcome.model_dump(mode="json"))
    assert settled.status_code == 200, settled.text
    assert settled.json()["settled_count"] == 1
