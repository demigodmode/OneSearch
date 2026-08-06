# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Versioned protocol endpoints used by remote indexing agents."""

import asyncio
import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from onesearch_shared import (
    MINIMUM_SUPPORTED_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
    AgentJobLease,
    AgentJobStatusResponse,
    BatchAck,
    DocumentBatch,
    JobCompletion,
    JobProgress,
    NormalizedRemoteDocument,
    ScanManifest,
    ScanManifestPage,
    ScanManifestPageAck,
    ScanPageOutcome,
    ScanPageOutcomeAck,
)
from onesearch_shared import (
    AgentHeartbeat as AgentHeartbeatRequest,
)
from sqlalchemy.orm import Session, sessionmaker

from ..db.database import get_db
from ..models import Agent
from ..schemas import AgentHeartbeatResponse
from ..services.agent_auth import (
    consume_enrollment_code,
    create_agent_token,
    get_authenticated_agent,
    hash_token,
    record_agent_activity,
    record_agent_heartbeat,
    require_approved_agent,
    require_remote_agents_enabled,
)
from ..services.agent_jobs import AgentJobService, JobConflict, JobLeaseError, JobNotFound
from ..services.remote_files import (
    RemoteFileChanged,
    RemoteFileError,
    RemoteFileMissing,
    RemoteStreamTimeout,
    extract_in_process,
    extract_uploads,
    remote_streams,
)
from ..services.remote_ingest import RemoteIngestService, canonical_remote_path
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


def _classify_stream_failure(request: JobCompletion) -> tuple[str, RemoteFileError]:
    """Accept only the two protocol error pairs safe for persistence and streaming."""
    reason = request.reason.value if request.reason else None
    if reason == "not_found" and request.detail == "remote_file_missing":
        return "remote_file_missing", RemoteFileMissing("remote file missing")
    if reason == "invalid_request" and request.detail == "remote_file_changed":
        return "remote_file_changed", RemoteFileChanged("remote file changed")
    return "remote_stream_failed", RemoteStreamTimeout("remote stream failed")


def _validate_enrollment(request: AgentEnrollmentRequest) -> None:
    if not MINIMUM_SUPPORTED_PROTOCOL_VERSION <= request.protocol_version <= PROTOCOL_VERSION:
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
        protocol_version=request.protocol_version,
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
    if not MINIMUM_SUPPORTED_PROTOCOL_VERSION <= request.protocol_version <= PROTOCOL_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Unsupported protocol version"
        )
    agent_status = record_agent_heartbeat(
        db,
        agent_id=agent.id,
        version=request.agent_version,
        platform=request.platform,
        protocol_version=request.protocol_version,
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


@router.get("/jobs/{job_id}/status", dependencies=[Depends(require_remote_agents_enabled)])
async def job_status(job_id: str, agent: ApprovedAgent, db: Database):
    try:
        job = AgentJobService(db).status_for_agent(job_id, agent.id)
    except JobNotFound as error:
        raise HTTPException(status_code=404, detail="job not found") from error
    return AgentJobStatusResponse(job_id=job.id, status=job.status)


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
        record_agent_activity(db, agent.id)
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
        result = await get_remote_ingest_service(db).accept_batch(
            agent.id, job_id, lease_token, request
        )
        db.commit()
        return result
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error


@router.post(
    "/jobs/{job_id}/manifest-pages",
    response_model=ScanManifestPageAck,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def submit_manifest_page(
    job_id: str,
    request: ScanManifestPage,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.page.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        result = get_remote_ingest_service(db).accept_manifest_page(
            agent.id, job_id, lease_token, request
        )
        db.commit()
        return result
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error


@router.post(
    "/jobs/{job_id}/page-outcomes",
    response_model=ScanPageOutcomeAck,
    dependencies=[Depends(require_remote_agents_enabled)],
)
async def submit_page_outcome(
    job_id: str,
    request: ScanPageOutcome,
    agent: ApprovedAgent,
    db: Database,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    if request.outcome.job_id != job_id or lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        result = get_remote_ingest_service(db).accept_page_outcome(
            agent.id, job_id, lease_token, request
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
        job = AgentJobService(db).validate_lease(agent.id, job_id, lease_token)
        if job.processing_mode == "on_server" and job.kind == "scan":
            if request.job_id != job_id or request.source_id != job.source_id:
                raise JobConflict("invalid remote manifest")
            jobs = AgentJobService(db)
            jobs.validate_manifest_retry(job, request.model_dump(mode="json"))
            files = []
            for item in request.files:
                path = canonical_remote_path(item.path)
                if item.path_hash != __import__("onesearch_shared").remote_path_hash(path):
                    raise JobConflict("manifest path hash mismatch")
                files.append({**item.model_dump(mode="json"), "path": path})
            manifest_payload = request.model_dump(mode="json")
            manifest_payload["files"] = files
            job.checkpoint = json.dumps(
                {"version": 1, "remote_manifest": manifest_payload},
                sort_keys=True,
                separators=(",", ":"),
            )
            selected_paths = (
                set(request.changed_paths) if request.changed_paths is not None else None
            )
            jobs.enqueue_extract_files(
                job,
                files
                if selected_paths is None
                else [item for item in files if item["path"] in selected_paths],
            )
        else:
            get_remote_ingest_service(db).accept_manifest(agent.id, job_id, lease_token, request)
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
        jobs = AgentJobService(db)
        job = jobs.validate_lease(agent.id, job_id, lease_token)
        stream_failure = (
            _classify_stream_failure(request)
            if job.kind == "stream_file" and request.status.value == "failed"
            else None
        )
        if (
            request.status.value == "succeeded"
            and job.kind == "scan"
            and job.processing_mode == "on_agent"
        ):
            await get_remote_ingest_service(db).reconcile_completion(agent.id, job_id, lease_token)
        elif (
            request.status.value == "succeeded"
            and job.kind == "scan"
            and job.processing_mode == "on_server"
        ):
            jobs.release_on_server_parent(job_id)
            await get_remote_ingest_service(db).settle_server_parent(job_id)
        else:
            jobs.complete(
                agent.id,
                job_id,
                lease_token,
                request.status.value,
                error=stream_failure[0] if stream_failure else request.detail,
                checkpoint=request.checkpoint.model_dump(mode="json")
                if request.checkpoint
                else None,
            )
            if job.kind == "extract_file" and job.processing_mode == "on_server":
                parent_id = json.loads(job.payload)["parent_job_id"]
                await get_remote_ingest_service(db).settle_server_parent(parent_id)
        db.commit()
        if job.kind == "extract_file" and request.status.value in {"failed", "cancelled"}:
            extract_uploads.cleanup(job_id)
        if job.kind == "stream_file" and request.status.value == "failed":
            await remote_streams.close(job_id, stream_failure[1])
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
        job = AgentJobService(db).acknowledge_cancellation(agent.id, job_id, lease_token)
        db.commit()
        if job.kind == "extract_file":
            extract_uploads.cleanup(job_id)
        if job.kind == "stream_file":
            await remote_streams.close(job_id, RemoteStreamTimeout("stream cancelled"))
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}


@router.put("/jobs/{job_id}/file-chunks", dependencies=[Depends(require_remote_agents_enabled)])
async def receive_file_chunk(
    job_id: str,
    request: Request,
    agent: ApprovedAgent,
    db: Database,
    sequence: int,
    checksum: str | None = None,
    complete: bool = False,
    stream_checksum: str | None = None,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    """Accept one bounded raw chunk; JSON parsing is intentionally never involved."""
    if lease_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        jobs = AgentJobService(db)
        job = jobs.validate_lease(agent.id, job_id, lease_token)
        if job.kind not in {"extract_file", "stream_file"}:
            raise JobConflict("invalid file transfer job")
        if job.kind == "extract_file":
            payload = json.loads(job.payload)
            if complete:
                if stream_checksum is None:
                    raise RemoteFileChanged("stream checksum required")
                temporary = extract_uploads.finish(
                    job_id, sequence=sequence, checksum=stream_checksum
                )
                try:
                    extracted = await extract_in_process(
                        str(temporary), job.source_id, payload["extraction"], 30
                    )
                    if extracted is None:
                        raise RemoteFileChanged("unsupported remote file")
                    result = NormalizedRemoteDocument(
                        source_id=job.source_id,
                        path=payload["path"],
                        title=extracted.title,
                        content=extracted.content,
                        size_bytes=payload["size_bytes"],
                        modified_at=payload["modified_at"],
                        metadata={**extracted.metadata, "type": extracted.type},
                    )
                    await get_remote_ingest_service(db).accept_server_document(
                        agent.id, job_id, lease_token, result
                    )
                    parent_id = payload["parent_job_id"]
                    await get_remote_ingest_service(db).settle_server_parent(parent_id)
                finally:
                    extract_uploads.cleanup(job_id)
            else:
                if checksum is None:
                    raise RemoteFileChanged("chunk checksum required")
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as error:
                        raise RemoteFileChanged("invalid chunk length") from error
                    if declared_length < 1 or declared_length > extract_uploads.chunk_bytes:
                        raise RemoteFileChanged("chunk exceeds limit")
                body = bytearray()
                async for part in request.stream():
                    body.extend(part)
                    if len(body) > extract_uploads.chunk_bytes:
                        raise RemoteFileChanged("chunk exceeds limit")
                extract_uploads.append(
                    job_id,
                    sequence=sequence,
                    data=bytes(body),
                    checksum=checksum,
                    expected_size=payload["size_bytes"],
                    maximum_size=payload["maximum_size"],
                    suffix=__import__("pathlib").Path(payload["path"]).suffix,
                )
        else:
            queue = remote_streams.require(job_id)
            if complete:
                if stream_checksum is None:
                    raise RemoteFileChanged("stream checksum required")
                queue.validate_finish(sequence, stream_checksum)
                jobs.complete(agent.id, job_id, lease_token, "succeeded")
                db.commit()
                await queue.finish(sequence, stream_checksum)
                return {"status": "ok"}
            else:
                if checksum is None:
                    raise RemoteFileChanged("chunk checksum required")
                body = bytearray()
                async for part in request.stream():
                    body.extend(part)
                    if len(body) > queue.max_bytes:
                        raise RemoteFileChanged("chunk exceeds limit")
                await queue.put(sequence, bytes(body), checksum)
        db.commit()
    except (RemoteFileChanged, RemoteStreamTimeout) as error:
        db.rollback()
        if "job" in locals() and job.kind == "extract_file":
            extract_uploads.cleanup(job_id)
        if "job" in locals() and job.kind == "stream_file":
            try:
                AgentJobService(db).cancel(job_id)
                db.commit()
            except JobConflict:
                db.rollback()
            finally:
                await remote_streams.close(job_id, error)
        raise HTTPException(
            status_code=409, detail={"code": error.code, "message": str(error)}
        ) from error
    except (JobNotFound, JobLeaseError, JobConflict) as error:
        db.rollback()
        raise _job_error(error) from error
    return {"status": "ok"}
