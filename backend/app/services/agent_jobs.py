"""Durable leasing and idempotent receipt handling for remote agent jobs."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from onesearch_shared import (
    REMOTE_MAX_BATCH_BYTES,
    REMOTE_MAX_BATCH_DOCUMENTS,
    REMOTE_MAX_ENTRIES_PER_DIRECTORY,
    REMOTE_MAX_SCAN_FILES,
    REMOTE_MAX_SNAPSHOT_BYTES,
    AgentJobLease,
    BatchAck,
    JobKind,
    ProcessingMode,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings as runtime_settings
from ..models import Agent, AgentBatch, AgentJob, Source
from .agent_auth import hash_token, verify_token
from .app_settings import AppSettingsService


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobNotFound(Exception):  # noqa: N818 - kept concise for HTTP error mapping
    """The job is not visible to this agent."""


class JobLeaseError(Exception):
    """The lease credential is absent, invalid, or expired."""


class JobConflict(Exception):  # noqa: N818 - kept concise for HTTP error mapping
    """The requested transition is not allowed."""


class AgentJobService:
    def __init__(self, db: Session, *, lease_seconds: int = 60):
        self.db = db
        self.lease_seconds = lease_seconds

    def status_for_agent(self, job_id: str, agent_id: str) -> AgentJob:
        job = self.db.get(AgentJob, job_id)
        if job is None or job.agent_id != agent_id:
            raise JobNotFound()
        return job

    def enqueue_scan(self, source: Source, *, full: bool, reason: str | None = None) -> AgentJob:
        if source.location_type != "agent" or source.agent_id is None:
            raise JobConflict("source is not remote")
        agent = self.db.get(Agent, source.agent_id)
        processing_mode = source.processing_mode
        if processing_mode is None:
            if agent is None:
                raise JobConflict("source agent is not available")
            processing_mode = agent.default_processing_mode
        known = {
            item.path: {
                "size_bytes": item.size_bytes,
                "modified_at": item.modified_at_ns
                if item.modified_at_ns is not None
                else (
                    int(
                        (
                            item.modified_at.replace(tzinfo=timezone.utc)
                            if item.modified_at.tzinfo is None
                            else item.modified_at
                        ).timestamp()
                        * 1_000_000_000
                    )
                    if item.modified_at is not None
                    else None
                ),
                "hash": item.hash,
                "status": item.status,
            }
            for item in source.indexed_files
        }
        # This is deliberately a small, explicit contract: an agent never has to
        # infer server-side defaults while it is extracting a file offline.
        agent_roots = json.loads(agent.allowed_roots) if processing_mode and agent else []
        root_id = next(
            (root["root_id"] for root in agent_roots if root.get("path") == source.root_path), None
        )
        settings = AppSettingsService(self.db).get_settings()
        extraction = {
            name: getattr(settings, name)
            for name in (
                "unsupported_file_policy",
                "media_metadata_mode",
                "raw_metadata_mode",
                "index_gps_metadata",
                "max_text_file_size_mb",
                "max_pdf_file_size_mb",
                "max_office_file_size_mb",
                "image_metadata_max_size_mb",
                "epub_extraction_max_size_mb",
                "comic_extraction_max_size_mb",
                "media_probe_max_size_mb",
            )
        }
        extraction["source_name"] = source.name
        extraction.update(
            {
                "text_extraction_timeout": runtime_settings.text_extraction_timeout,
                "pdf_extraction_timeout": runtime_settings.pdf_extraction_timeout,
                "office_extraction_timeout": runtime_settings.office_extraction_timeout,
                "raw_metadata_timeout_seconds": runtime_settings.raw_metadata_timeout_seconds,
            }
        )
        payload = {
            "full": full,
            "root_id": root_id,
            "root_path": source.root_path,
            "include_patterns": json.loads(source.include_patterns)
            if source.include_patterns
            else None,
            "exclude_patterns": json.loads(source.exclude_patterns)
            if source.exclude_patterns
            else None,
            "known_files": known,
            "extraction": extraction,
            "limits": {
                "max_snapshot_bytes": REMOTE_MAX_SNAPSHOT_BYTES,
                "max_batch_documents": REMOTE_MAX_BATCH_DOCUMENTS,
                "max_batch_bytes": REMOTE_MAX_BATCH_BYTES,
                "max_scan_files": REMOTE_MAX_SCAN_FILES,
                "max_entries_per_directory": REMOTE_MAX_ENTRIES_PER_DIRECTORY,
            },
        }
        job = AgentJob(
            id=secrets.token_urlsafe(18),
            agent_id=source.agent_id,
            source_id=source.id,
            kind="scan",
            reason=reason,
            status="pending",
            processing_mode=processing_mode,
            active_key=source.id,
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            checkpoint="{}",
        )
        try:
            with self.db.begin_nested():
                self.db.add(job)
                self.db.flush()
            return job
        except IntegrityError:
            winner = self.db.scalar(select(AgentJob).where(AgentJob.active_key == source.id))
            if winner is None:
                raise
            return winner

    def enqueue_browse(self, agent_id: str, root_path: str) -> AgentJob:
        digest = hashlib.sha256(root_path.encode("utf-8")).hexdigest()
        active_key = f"browse:{agent_id}:{digest}"
        job = AgentJob(
            id=secrets.token_urlsafe(18),
            agent_id=agent_id,
            source_id=None,
            kind="browse",
            reason="validate",
            status="pending",
            processing_mode=None,
            active_key=active_key,
            payload=json.dumps({"operation": "validate", "root_path": root_path}),
            checkpoint="{}",
        )
        try:
            with self.db.begin_nested():
                self.db.add(job)
                self.db.flush()
            return job
        except IntegrityError:
            winner = self.db.scalar(select(AgentJob).where(AgentJob.active_key == active_key))
            if winner is None:
                raise
            return winner

    def enqueue_extract_files(self, scan_job: AgentJob, files: list[dict]) -> list[AgentJob]:
        """Fan an on-server scan manifest into independently leased file transfers."""
        if (
            scan_job.kind != "scan"
            or scan_job.processing_mode != "on_server"
            or not scan_job.source_id
        ):
            raise JobConflict("on-server scan required")
        scan_payload = json.loads(scan_job.payload)
        limits, extraction = scan_payload["limits"], scan_payload["extraction"]
        jobs = []
        for item in files:
            path, size = item["path"], item["size_bytes"]
            active_key = f"extract:{scan_job.id}:{hashlib.sha256(path.encode()).hexdigest()}"
            existing = self.db.scalar(select(AgentJob).where(AgentJob.active_key == active_key))
            if existing is not None:
                jobs.append(existing)
                continue
            payload = {
                "parent_job_id": scan_job.id,
                "root_id": scan_payload["root_id"],
                "path": path,
                "size_bytes": size,
                "modified_at": item["modified_at"],
                "content_hash": item.get("content_hash"),
                "maximum_size": limits["max_snapshot_bytes"],
                "extraction": extraction,
            }
            child = AgentJob(
                id=secrets.token_urlsafe(18),
                agent_id=scan_job.agent_id,
                source_id=scan_job.source_id,
                kind="extract_file",
                status="pending",
                processing_mode="on_server",
                active_key=active_key,
                payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                checkpoint="{}",
            )
            if size > limits["max_snapshot_bytes"]:
                child.status, child.error, child.completed_at, child.active_key = (
                    "failed", "remote file exceeds snapshot limit", _now(), None
                )
            self.db.add(child)
            jobs.append(child)
        self.db.flush()
        return jobs

    def validate_manifest_retry(self, scan_job: AgentJob, manifest: dict) -> None:
        """A parent manifest is immutable once fan-out has started."""
        checkpoint = json.loads(scan_job.checkpoint or "{}")
        existing = checkpoint.get("remote_manifest") if checkpoint.get("version") == 1 else None
        if existing is not None and json.dumps(existing, sort_keys=True, separators=(",", ":")) != json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ):
            raise JobConflict("remote manifest conflict")

    def enqueue_stream_file(
        self, source: Source, *, path: str, size_bytes: int, modified_at: int
    ) -> AgentJob:
        if source.location_type != "agent" or not source.agent_id:
            raise JobConflict("source is not remote")
        agent = self.db.get(Agent, source.agent_id)
        roots = json.loads(agent.allowed_roots) if agent else []
        root_id = next(
            (root["root_id"] for root in roots if root.get("path") == source.root_path), None
        )
        if not root_id:
            raise JobConflict("remote root is unavailable")
        job = AgentJob(
            id=secrets.token_urlsafe(18),
            agent_id=source.agent_id,
            source_id=source.id,
            kind="stream_file",
            status="pending",
            processing_mode="on_server",
            active_key=f"stream:{secrets.token_urlsafe(18)}",
            payload=json.dumps(
                {
                    "root_id": root_id,
                    "path": path,
                    "size_bytes": size_bytes,
                    "modified_at": modified_at,
                    "maximum_size": size_bytes,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            checkpoint="{}",
        )
        with self.db.begin_nested():
            self.db.add(job)
            self.db.flush()
        return job

    def fail_expired_leases(self) -> int:
        now = _now()
        result = self.db.execute(
            update(AgentJob)
            .where(AgentJob.status.in_(("claimed", "running")), AgentJob.lease_expires_at <= now)
            .values(status="pending", lease_token_hash=None, lease_expires_at=None)
        )
        cancelling = self.db.execute(
            update(AgentJob)
            .where(AgentJob.status == "cancelling", AgentJob.lease_expires_at <= now)
            .values(
                status="cancelled",
                completed_at=now,
                active_key=None,
                lease_token_hash=None,
                lease_expires_at=None,
            )
        )
        self.finalize_cancelled_server_parents()
        return result.rowcount + cancelling.rowcount

    def finalize_cancelled_server_parents(self, parent_ids=None) -> int:
        parents = self.db.scalars(
            select(AgentJob).where(
                AgentJob.kind == "scan", AgentJob.processing_mode == "on_server", AgentJob.status == "cancelling"
            )
        )
        count = 0
        for parent in parents:
            if parent_ids is not None and parent.id not in parent_ids:
                continue
            children = [
                child for child in self.db.scalars(select(AgentJob).where(AgentJob.kind == "extract_file"))
                if json.loads(child.payload).get("parent_job_id") == parent.id
            ]
            if all(child.status in {"completed", "failed", "cancelled"} for child in children):
                parent.status, parent.active_key, parent.completed_at = "cancelled", None, _now()
                count += 1
        return count

    def claim_next(self, agent_id: str) -> AgentJobLease | None:
        self.fail_expired_leases()
        # Conditional update is the actual lock: a simultaneous selector cannot win it twice.
        for _ in range(3):
            job_id = self.db.scalar(
                select(AgentJob.id)
                .where(
                    AgentJob.agent_id == agent_id,
                    AgentJob.status == "pending",
                    AgentJob.kind.in_(("scan", "browse", "extract_file", "stream_file")),
                )
                .order_by(AgentJob.created_at, AgentJob.id)
                .limit(1)
            )
            if job_id is None:
                return None
            token = secrets.token_urlsafe(32)
            expiry = _now() + timedelta(seconds=self.lease_seconds)
            claimed = self.db.execute(
                update(AgentJob)
                .where(
                    AgentJob.id == job_id,
                    AgentJob.agent_id == agent_id,
                    AgentJob.status == "pending",
                )
                .values(
                    status="claimed",
                    attempts=AgentJob.attempts + 1,
                    lease_token_hash=hash_token(token),
                    lease_expires_at=expiry,
                )
            )
            if claimed.rowcount != 1:
                continue
            job = self.db.get(AgentJob, job_id)
            return AgentJobLease(
                id=job.id,
                kind=JobKind(job.kind),
                source_id=job.source_id,
                processing_mode=ProcessingMode(job.processing_mode)
                if job.processing_mode
                else None,
                payload=json.loads(job.payload),
                lease_token=token,
            )
        return None

    def _leased_job(
        self, agent_id: str, job_id: str, token: str, *, active: bool = True
    ) -> AgentJob:
        job = self.db.get(AgentJob, job_id)
        if job is None or job.agent_id != agent_id:
            raise JobNotFound()
        if job.lease_token_hash is None or not verify_token(token, job.lease_token_hash):
            raise JobLeaseError()
        if job.lease_expires_at is None or job.lease_expires_at <= _now():
            raise JobLeaseError()
        if active and job.status not in {"claimed", "running"}:
            raise JobConflict()
        return job

    def validate_lease(self, agent_id: str, job_id: str, token: str) -> AgentJob:
        """Public lease validation for operations with external side effects."""
        return self._leased_job(agent_id, job_id, token)

    def lock_active_lease(self, agent_id: str, job_id: str, token: str) -> AgentJob:
        """Serialize an active lease's external side effects until this request commits."""
        now = _now()
        locked = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == job_id,
                AgentJob.agent_id == agent_id,
                AgentJob.lease_token_hash == hash_token(token),
                AgentJob.lease_expires_at > now,
                AgentJob.status.in_(("claimed", "running")),
            )
            .values(progress_current=AgentJob.progress_current)
        )
        if locked.rowcount != 1:
            self._leased_job(agent_id, job_id, token)
            raise JobConflict()
        return self.db.get(AgentJob, job_id)

    def extend_lease(
        self,
        agent_id: str,
        job_id: str,
        token: str,
        *,
        completed_items: int | None = None,
        total_items: int | None = None,
        checkpoint: dict | None = None,
    ) -> AgentJob:
        now = _now()
        values = {
            "status": "running",
            "lease_expires_at": now + timedelta(seconds=self.lease_seconds),
        }
        if completed_items is not None:
            values["progress_current"] = completed_items
        if total_items is not None:
            values["progress_total"] = total_items
        if checkpoint is not None:
            values["checkpoint"] = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
        result = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == job_id,
                AgentJob.agent_id == agent_id,
                AgentJob.lease_token_hash == hash_token(token),
                AgentJob.lease_expires_at > now,
                AgentJob.status.in_(("claimed", "running")),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self._leased_job(agent_id, job_id, token)
            raise JobConflict()
        return self.db.get(AgentJob, job_id)

    def accept_batch(
        self, agent_id: str, job_id: str, token: str, idempotency_key: str, payload: dict
    ) -> BatchAck:
        self.lock_active_lease(agent_id, job_id, token)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        checksum = hashlib.sha256(canonical.encode()).hexdigest()
        existing = self.db.scalar(
            select(AgentBatch).where(
                AgentBatch.job_id == job_id, AgentBatch.idempotency_key == idempotency_key
            )
        )
        if existing:
            if existing.checksum != checksum:
                raise JobConflict()
            return BatchAck(
                batch_id=idempotency_key,
                accepted_count=len(payload.get("documents", [])),
                duplicate=True,
            )
        try:
            with self.db.begin_nested():
                self.db.add(
                    AgentBatch(job_id=job_id, idempotency_key=idempotency_key, checksum=checksum)
                )
                self.db.flush()
        except IntegrityError as error:
            existing = self.db.scalar(
                select(AgentBatch).where(
                    AgentBatch.job_id == job_id, AgentBatch.idempotency_key == idempotency_key
                )
            )
            if existing is None or existing.checksum != checksum:
                raise JobConflict() from error
            return BatchAck(
                batch_id=idempotency_key,
                accepted_count=len(payload.get("documents", [])),
                duplicate=True,
            )
        return BatchAck(
            batch_id=idempotency_key,
            accepted_count=len(payload.get("documents", [])),
            duplicate=False,
        )

    def complete(
        self,
        agent_id: str,
        job_id: str,
        token: str,
        status: str,
        *,
        error: str | None = None,
        checkpoint: dict | None = None,
    ) -> AgentJob:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise JobConflict()
        guarded = self._leased_job(agent_id, job_id, token, active=False)
        if (
            status == "succeeded"
            and guarded.kind == "scan"
            and guarded.processing_mode == "on_agent"
        ):
            raise JobConflict("on-agent scan requires reconciliation")
        now = _now()
        allowed = ("cancelling",) if status == "cancelled" else ("claimed", "running")
        values = {
            "status": {"succeeded": "completed", "failed": "failed", "cancelled": "cancelled"}[
                status
            ],
            "error": error,
            "completed_at": now,
            "active_key": None,
            "lease_token_hash": None,
            "lease_expires_at": None,
        }
        if checkpoint is not None:
            values["checkpoint"] = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
        result = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == job_id,
                AgentJob.agent_id == agent_id,
                AgentJob.lease_token_hash == hash_token(token),
                AgentJob.lease_expires_at > now,
                AgentJob.status.in_(allowed),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self._leased_job(agent_id, job_id, token, active=False)
            raise JobConflict()
        return self.db.get(AgentJob, job_id)

    def complete_reconciled_scan(self, agent_id: str, job_id: str, token: str) -> AgentJob:
        now = _now()
        result = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == job_id,
                AgentJob.agent_id == agent_id,
                AgentJob.kind == "scan",
                AgentJob.processing_mode == "on_agent",
                AgentJob.lease_token_hash == hash_token(token),
                AgentJob.lease_expires_at > now,
                AgentJob.status.in_(("claimed", "running")),
            )
            .values(
                status="completed",
                completed_at=now,
                active_key=None,
                lease_token_hash=None,
                lease_expires_at=None,
            )
        )
        if result.rowcount != 1:
            self._leased_job(agent_id, job_id, token, active=False)
            raise JobConflict()
        return self.db.get(AgentJob, job_id)

    def release_on_server_parent(self, job_id: str) -> AgentJob:
        """The scan lease is done, but its active key remains until child extraction settles."""
        job = self.db.get(AgentJob, job_id)
        if job is None or job.kind != "scan" or job.processing_mode != "on_server":
            raise JobConflict("on-server scan required")
        if job.status not in {"claimed", "running"}:
            raise JobConflict("scan is not active")
        job.status, job.lease_token_hash, job.lease_expires_at = "running", None, None
        return job

    def settle_on_server_parent(self, job_id: str) -> str:
        """Return readiness only; ingestion owns terminal reconciliation/deletion."""
        parent = self.db.get(AgentJob, job_id)
        if parent is None or parent.kind != "scan" or parent.processing_mode != "on_server":
            raise JobConflict("on-server scan required")
        return parent.status

    def cancel(self, job_id: str) -> AgentJob:
        now = _now()
        pending = self.db.execute(
            update(AgentJob)
            .where(AgentJob.id == job_id, AgentJob.status == "pending")
            .values(
                status="cancelled",
                completed_at=now,
                active_key=None,
                lease_token_hash=None,
                lease_expires_at=None,
            )
        )
        if pending.rowcount == 0:
            self.db.execute(
                update(AgentJob)
                .where(AgentJob.id == job_id, AgentJob.status.in_(("claimed", "running")))
                .values(status="cancelling")
            )
        job = self.db.get(AgentJob, job_id)
        if job is None:
            raise JobNotFound()
        if job.kind == "scan" and job.processing_mode == "on_server":
            children = [
                child for child in self.db.scalars(select(AgentJob).where(AgentJob.kind == "extract_file"))
                if json.loads(child.payload).get("parent_job_id") == job.id
            ]
            for child in children:
                if child.status == "pending":
                    child.status, child.active_key, child.completed_at = "cancelled", None, now
                elif child.status in {"claimed", "running"}:
                    child.status = "cancelling"
        if job.status not in {"cancelling", "completed", "failed", "cancelled"}:
            raise JobConflict()
        return job

    def acknowledge_cancellation(self, agent_id: str, job_id: str, token: str) -> AgentJob:
        """Finalize only an agent-held cancellation request."""
        now = _now()
        result = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == job_id,
                AgentJob.agent_id == agent_id,
                AgentJob.lease_token_hash == hash_token(token),
                AgentJob.lease_expires_at > now,
                AgentJob.status == "cancelling",
            )
            .values(
                status="cancelled",
                completed_at=now,
                active_key=None,
                lease_token_hash=None,
                lease_expires_at=None,
            )
        )
        if result.rowcount != 1:
            self._leased_job(agent_id, job_id, token, active=False)
            raise JobConflict()
        job = self.db.get(AgentJob, job_id)
        if job.kind == "extract_file":
            self.finalize_cancelled_server_parents([json.loads(job.payload).get("parent_job_id")])
        return job
