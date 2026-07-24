"""Durable leasing and idempotent receipt handling for remote agent jobs."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from onesearch_shared import AgentJobLease, BatchAck, JobKind, ProcessingMode
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Agent, AgentBatch, AgentJob, Source
from .agent_auth import hash_token, verify_token


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

    def enqueue_scan(self, source: Source, *, full: bool, reason: str | None = None) -> AgentJob:
        if source.location_type != "agent" or source.agent_id is None:
            raise JobConflict("source is not remote")
        processing_mode = source.processing_mode
        if processing_mode is None:
            agent = self.db.get(Agent, source.agent_id)
            if agent is None:
                raise JobConflict("source agent is not available")
            processing_mode = agent.default_processing_mode
        job = AgentJob(
            id=secrets.token_urlsafe(18),
            agent_id=source.agent_id,
            source_id=source.id,
            kind="scan",
            reason=reason,
            status="pending",
            processing_mode=processing_mode,
            active_key=source.id,
            payload=json.dumps({"full": full}),
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
        return result.rowcount + cancelling.rowcount

    def claim_next(self, agent_id: str) -> AgentJobLease | None:
        self.fail_expired_leases()
        # Conditional update is the actual lock: a simultaneous selector cannot win it twice.
        for _ in range(3):
            job_id = self.db.scalar(
                select(AgentJob.id)
                .where(AgentJob.agent_id == agent_id, AgentJob.status == "pending")
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
        return self.db.get(AgentJob, job_id)
