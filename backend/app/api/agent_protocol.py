# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Versioned protocol endpoints used by remote indexing agents."""

import asyncio
import hashlib
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
    BrowseResult,
    DocumentBatch,
    JobCompletion,
    JobProgress,
    NormalizedRemoteDocument,
    ScanManifestPage,
    ScanManifestPageAck,
    ScanPageOutcome,
    ScanPageOutcomeAck,
)
from onesearch_shared import (
    AgentHeartbeat as AgentHeartbeatRequest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.database import get_db
from ..models import Agent, AgentScanEntry
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


def _validated_browse_result(job, result: BrowseResult) -> dict:
    """Bind a directory-only result to the immutable server-issued list request."""
    try:
        payload = json.loads(job.payload)
    except (TypeError, json.JSONDecodeError) as error:
        raise JobConflict("invalid browse payload") from error
    if (
        job.kind != "browse"
        or job.reason != "browse"
        or not isinstance(payload, dict)
        or payload.get("operation") != "list"
        or result.root_id != payload.get("root_id")
        or result.path != payload.get("path")
    ):
        raise JobConflict("browse result does not match job")
    expected_paths = [
        f"{result.path}/{entry.name}".strip("/") for entry in result.entries
    ]
    if [entry.path for entry in result.entries] != expected_paths:
        raise JobConflict("browse result contains non-child entries")
    if [entry.name for entry in result.entries] != sorted(
        (entry.name for entry in result.entries), key=lambda name: (name.casefold(), name)
    ):
        raise JobConflict("browse result is not deterministic")
    return result.model_dump(mode="json")


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
    try:
        agent_status = record_agent_heartbeat(
            db, agent_id=agent.id, version=request.agent_version, platform=request.platform,
            protocol_version=request.protocol_version, update_report=request.update_report,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
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
    timeout_seconds = db.info.get("claim_timeout_seconds", CLAIM_TIMEOUT_SECONDS)
    poll_seconds = db.info.get("claim_poll_seconds", CLAIM_POLL_SECONDS)
    deadline = claim_clock() + timeout_seconds
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
        await claim_sleep(min(poll_seconds, remaining))
    from fastapi.responses import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs/{job_id}/status", dependencies=[Depends(require_remote_agents_enabled)])
async def job_status(job_id: str, agent: ApprovedAgent, db: Database):
    try:
        job = AgentJobService(db).status_for_agent(job_id, agent.id)
    except (JobNotFound) as error:
        raise HTTPException(status_code=404, detail="job not found") from error
    response = AgentJobStatusResponse(
        job_id=job.id,
        status=job.status,
        handoff_released=AgentJobService.on_server_handoff_released(job),
    )
    return response


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
        browse_result = None
        if request.browse_result is not None:
            browse_result = _validated_browse_result(job, request.browse_result)
        elif (
            request.status.value == "succeeded"
            and job.kind == "browse"
            and job.reason == "browse"
        ):
            raise JobConflict("browse list completion requires a result")
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
            get_remote_ingest_service(db).enqueue_staged_server_extractions(
                agent.id, job_id, lease_token
            )
            jobs.release_on_server_parent(job_id)
            await get_remote_ingest_service(db).settle_server_parent(job_id)
        else:
            jobs.complete(
                agent.id,
                job_id,
                lease_token,
                request.status.value,
                error=stream_failure[0] if stream_failure else request.detail,
                checkpoint=(
                    {"browse_result": browse_result}
                    if browse_result is not None
                    else request.checkpoint.model_dump(mode="json")
                    if request.checkpoint
                    else None
                ),
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


@router.put("/jobs/{job_id}/previews", dependencies=[Depends(require_remote_agents_enabled)])
async def receive_preview(
    job_id: str,
    request: Request,
    agent: ApprovedAgent,
    db: Database,
    path: str | None = None,
    modified_at_ns: int | None = None,
    checksum: str | None = None,
    lease_token: Annotated[str | None, Header(alias=LEASE_TOKEN_HEADER)] = None,
):
    """Accept a bounded derived JPEG preview from an agent for offline viewing."""
    if lease_token is None or path is None or modified_at_ns is None:
        raise HTTPException(status_code=401, detail="Invalid or expired job lease")
    try:
        jobs = AgentJobService(db)
        job = jobs.validate_lease(agent.id, job_id, lease_token)

        try:
            payload = json.loads(job.payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise JobConflict("invalid preview job") from error

        # Previews are produced only by changed paths from an active v3 on-agent scan.
        if (
            job.kind != "scan"
            or job.source_id is None
            or job.processing_mode != "on_agent"
            or agent.protocol_version != 3
            or not isinstance(payload, dict)
            or type(payload.get("protocol_version")) is not int
            or payload["protocol_version"] != 3
        ):
            raise JobConflict("invalid preview job")

        # Validate and canonicalize path
        canonical_path = canonical_remote_path(path)
        staged_entry = db.scalar(
            select(AgentScanEntry.id).where(
                AgentScanEntry.job_id == job.id,
                AgentScanEntry.path == canonical_path,
                AgentScanEntry.modified_at_ns == modified_at_ns,
                AgentScanEntry.needs_processing.is_(True),
            )
        )
        if staged_entry is None:
            raise JobConflict("invalid preview target")

        # Read bounded preview body
        from app.config import settings as runtime_settings
        from app.services.preview_assets import (
            app_data_preview_directory,
            is_valid_derived_jpeg,
            store_preview_if_absent_or_identical,
        )

        max_preview_bytes = 2 * 1024 * 1024
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > max_preview_bytes:
                raise RemoteFileChanged("preview exceeds size limit")

        if not body:
            raise RemoteFileChanged("preview body is empty")

        # Verify checksum if provided
        if checksum is not None and hashlib.sha256(bytes(body)).hexdigest() != checksum:
            raise RemoteFileChanged("preview checksum mismatch")
        if not is_valid_derived_jpeg(bytes(body)):
            raise RemoteFileChanged("invalid preview body")

        # Preserve idempotent retries, but never let a conflicting retry overwrite a preview.
        preview_base = app_data_preview_directory(runtime_settings.database_url)
        stored = store_preview_if_absent_or_identical(
            job.source_id, canonical_path, bytes(body), preview_base, modified_at_ns
        )
        if stored is False:
            raise RemoteFileChanged("preview body conflict")
        if stored is None:
            raise RemoteFileChanged("preview storage failed")

        db.commit()
    except (RemoteFileChanged, JobLeaseError, JobConflict) as error:
        db.rollback()
        if isinstance(error, RemoteFileChanged):
            raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
        raise _job_error(error) from error
    except JobNotFound as error:
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

                    # Generate derived preview for browser-displayable images
                    preview_bytes = None
                    if extracted.type == "image":
                        from pathlib import Path as PathlibPath

                        from app.config import settings as runtime_settings
                        from app.services.preview_assets import (
                            app_data_preview_directory,
                            generate_derived_jpeg_preview,
                            is_browser_displayable_image,
                            store_preview,
                        )

                        extension = PathlibPath(payload["path"]).suffix.lstrip(".").lower()
                        if is_browser_displayable_image(extension):
                            preview_bytes = await asyncio.to_thread(
                                generate_derived_jpeg_preview, str(temporary)
                            )
                            if preview_bytes:
                                preview_base = app_data_preview_directory(runtime_settings.database_url)
                                store_preview(job.source_id, payload["path"], preview_bytes, preview_base, modified_at_ns=payload["modified_at"])

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
