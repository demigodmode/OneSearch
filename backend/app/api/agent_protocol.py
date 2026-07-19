# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Versioned protocol endpoints used by remote indexing agents."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from onesearch_shared import (
    PROTOCOL_VERSION,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
)
from onesearch_shared import (
    AgentHeartbeat as AgentHeartbeatRequest,
)
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Agent
from ..schemas import AgentHeartbeatResponse
from ..services.agent_auth import (
    consume_enrollment_code,
    create_agent_token,
    get_authenticated_agent,
    hash_token,
    record_agent_heartbeat,
    require_remote_agents_enabled,
)

router = APIRouter(prefix="/api/agent/v1", tags=["agent-protocol"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedAgent = Annotated[Agent, Depends(get_authenticated_agent)]


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
