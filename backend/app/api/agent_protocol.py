# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Versioned protocol endpoints used by remote indexing agents."""

import asyncio
import hashlib
import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from onesearch_shared import (
    PROTOCOL_VERSION,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
    AgentJobLease,
    BatchAck,
    DocumentBatch,
    JobCompletion,
    JobProgress,
    ScanManifest,
)
from onesearch_shared import (
    AgentHeartbeat as AgentHeartbeatRequest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.database import get_db
from ..models import Agent, AgentBatch
from ..schemas import AgentHeartbeatResponse
from ..services.agent_auth import (
    consume_enrollment_code,
    create_agent_token,
    get_authenticated_agent,
    hash_token,
    record_agent_heartbeat,
    require_approved_agent,
    require_remote_agents_enabled,
)
from ..services.agent_jobs import AgentJobService, JobConflict, JobLeaseError, JobNotFound
from ..services.remote_ingest import RemoteIngestService
from ..services.search import meili_service

router = APIRouter(prefix="/api/agent/v1", tags=["agent-protocol"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedAgent = Annotated[Agent, Depends(get_authenticated_agent)]
ApprovedAgent = Annotated[Agent, Depends(require_approved_agent)]
LEASE_TOKEN_HEADER = "X-OneSearch-Lease-Token"
CLAIM_TIMEOUT_SECONDS = 25
CLAIM_POLL_SECONDS = 1
claim_clock = time.monotonic
claim_sleep = asyncio.sleep


def get_remote_ingest_service(db: Session) -> RemoteIngestService:
    return RemoteIngestService(db, meili_service)


def make_claim_session(db: Session) -> Session:
    """Create an isolated queue-poll session on the request database bind."""
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()


def _job_error(error: Exception) -> HTTPException:
    if isinstance(error, JobNotFound):
        return HTTPException(status_code=404, detail="Job not found")
    if isinstance(error, JobLeaseError):
        return HTTPException(status_code=401, detail="Invalid or expired job lease")
    return HTTPException(status_code=409, detail="Job state conflict")


def _validate_enrollment(request: AgentEnrollmentRequest) -> None:
    if request.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported protocol version",
        )
    identity_values = (
        (request.agent_name, 120),
        (request.agent_version, 40),
        (request.platform, 80),
    )
    if any(not value.strip() or len(value) > maximum for value, maximum in identity_values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid agent identity"
        )
    root_ids = [root.root_id for root in request.allowed_roots]
    if len(root_ids) != len(set(root_ids)) or any(
        not root.root_id.strip() or not root.path.strip() for root in request.allowed_roots
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid allowed roots"
        )


@router.post(
    "/enroll",
    response_model=AgentEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def enroll_agent(request: AgentEnrollmentRequest, db: Database):
    _validate_enrollment(request)
    if not consume_enrollment_code(db, request.enrollment_token):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enrollment code is invalid, expired, or already used",
        )

    raw_token = create_agent_token()
    agent = Agent(
        id=str(uuid.uuid4()),
        name=request.agent_name.strip(),
        platform=request.platform.strip(),
        version=request.agent_version.strip(),
        protocol_version=request.protocol_version,
        token_hash=hash_token(raw_token),
        allowed_roots=json.dumps([root.model_dump(mode="json") for root in request.allowed_roots]),
        status="pending",
    )
    db.add(agent)
    db.commit()
    return AgentEnrollmentResponse(
        agent_id=agent.id,
        agent_token=raw_token,
        allowed_roots=request.allowed_roots,
    )


@router.post("/revoke-self", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_self(agent: AuthenticatedAgent, db: Database):
    """Let a newly enrolled agent invalidate itself if local persistence fails."""
    agent.status = "revoked"
    db.commit()


@router.post(
    "/heartbeat",
    response_model=AgentHeartbeatResponse,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def heartbeat(
    request: AgentHeartbeatRequest,
    agent: AuthenticatedAgent,
    db: Database,
):
    if request.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Unsupported protocol version"
        )
    agent_status = record_agent_heartbeat(
        db,
        agent_id=agent.id,
        version=request.agent_version,
        platform=request.platform,
    )
    if agent_status is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active")
    db.commit()
    return AgentHeartbeatResponse(status=agent_status)


@router.post(
    "/jobs/claim",
    response_model=AgentJobLease,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def claim_job(agent: ApprovedAgent, db: Database):
    """Long poll without retaining the request transaction while waiting."""
    deadline = claim_clock() + CLAIM_TIMEOUT_SECONDS
    while True:
        poll_db = make_claim_session(db)
        try:
            lease = AgentJobService(poll_db).claim_next(agent.id)
            if lease is not None:
                poll_db.commit()
                return lease
            poll_db.rollback()
        finally:
            poll_db.close()
        remaining = deadline - claim_clock()
        if remaining <= 0:
            break
        await claim_sleep(min(CLAIM_POLL_SECONDS, remaining))
    from fastapi.responses import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/jobs/{job_id}/heartbeat", dependencies=[Depends(require_remote_agents_enabled)])
async def job_heartbeat(
    job_id: str,
    request: JobProgress,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        AgentJobService(db).extend_lease(
            agent.id,
            job_id,
            lease_token,
            completed_items=request.completed_items,
            total_items=request.total_items,
        )
        db.commit()
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}


@router.post(
    "/jobs/{job_id}/batches",
    response_model=BatchAck,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def submit_batch(
    job_id: str,
    request: DocumentBatch,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        jobs = AgentJobService(db)
        leased = jobs._leased_job(agent.id, job_id, lease_token)
        canonical = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        checksum = hashlib.sha256(canonical.encode()).hexdigest()
        previous = db.scalar(
            select(AgentBatch).where(
                AgentBatch.job_id == job_id, AgentBatch.idempotency_key == request.batch_id
            )
        )
        if previous is not None and previous.checksum != checksum:
            raise JobConflict()
        if leased.processing_mode == "on_agent" and previous is None:
            await get_remote_ingest_service(db).ingest(agent.id, job_id, request)
        result = jobs.accept_batch(
            agent.id, job_id, lease_token, request.batch_id, request.model_dump(mode="json")
        )
        db.commit()
        return result
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error


@router.post("/jobs/{job_id}/manifest", dependencies=[Depends(require_remote_agents_enabled)])
async def submit_manifest(
    job_id: str,
    request: ScanManifest,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        jobs = AgentJobService(db)
        jobs._leased_job(agent.id, job_id, lease_token)
        get_remote_ingest_service(db).store_manifest(agent.id, job_id, request)
        db.commit()
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}


@router.post("/jobs/{job_id}/complete", dependencies=[Depends(require_remote_agents_enabled)])
async def complete_job(
    job_id: str,
    request: JobCompletion,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        AgentJobService(db).complete(
            agent.id,
            job_id,
            lease_token,
            request.status.value,
            error=request.detail,
            checkpoint=request.checkpoint.model_dump(mode="json") if request.checkpoint else None,
        )
        db.commit()
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}


@router.post("/jobs/{job_id}/cancel-ack", dependencies=[Depends(require_remote_agents_enabled)])
async def acknowledge_cancellation(
    job_id: str,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        AgentJobService(db).acknowledge_cancellation(agent.id, job_id, lease_token)
        db.commit()
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}
