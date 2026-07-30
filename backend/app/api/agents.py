# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Administrator APIs for remote indexing agents."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Agent, AgentEnrollment, AgentJob, IndexedFile, Source, User
from ..schemas import (
    AgentAdminDetails,
    AgentAdminResponse,
    AgentAdminSummary,
    AgentAdminUpdate,
    AgentEnrollmentCodeResponse,
    AgentJobSummary,
    AgentSourceSummary,
)
from ..services.agent_auth import create_enrollment_code, hash_token, require_remote_agents_enabled
from .auth import get_current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
RemoteAgentsEnabled = Annotated[None, Depends(require_remote_agents_enabled)]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _summaries(agent_ids: list[str], db: Session) -> dict[str, AgentAdminSummary]:
    summaries = {agent_id: AgentAdminSummary(attached_sources=0, indexed_documents=0, pending_jobs=0, active_jobs=0, failed_jobs=0, earliest_next_scan_at=None) for agent_id in agent_ids}
    if not agent_ids:
        return summaries
    for agent_id, source_count, earliest in db.query(Source.agent_id, func.count(Source.id), func.min(Source.next_scan_at)).filter(Source.agent_id.in_(agent_ids)).group_by(Source.agent_id):
        summaries[agent_id] = summaries[agent_id].model_copy(update={'attached_sources': source_count, 'earliest_next_scan_at': earliest})
    for agent_id, document_count in db.query(Source.agent_id, func.count(IndexedFile.id)).join(IndexedFile, IndexedFile.source_id == Source.id).filter(Source.agent_id.in_(agent_ids), IndexedFile.status == 'success').group_by(Source.agent_id):
        summaries[agent_id] = summaries[agent_id].model_copy(update={'indexed_documents': document_count})
    for agent_id, pending, active, failed in db.query(AgentJob.agent_id, func.sum(case((AgentJob.status == 'pending', 1), else_=0)), func.sum(case((AgentJob.status.in_(['claimed', 'running', 'cancelling']), 1), else_=0)), func.sum(case((AgentJob.status == 'failed', 1), else_=0))).filter(AgentJob.agent_id.in_(agent_ids)).group_by(AgentJob.agent_id):
        summaries[agent_id] = summaries[agent_id].model_copy(update={'pending_jobs': pending or 0, 'active_jobs': active or 0, 'failed_jobs': failed or 0})
    return summaries


def _response(agent: Agent, summary: AgentAdminSummary) -> AgentAdminResponse:
    return AgentAdminResponse(
        id=agent.id,
        name=agent.name,
        platform=agent.platform,
        version=agent.version,
        protocol_version=agent.protocol_version,
        allowed_roots=json.loads(agent.allowed_roots),
        default_processing_mode=agent.default_processing_mode,
        auto_update=agent.auto_update,
        status=agent.status,
        approved_at=agent.approved_at,
        last_seen_at=agent.last_seen_at,
        disabled_at=agent.disabled_at,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        summary=summary,
    )


def _detail_response(agent: Agent, db: Session) -> AgentAdminDetails:
    sources = db.query(Source).filter(Source.agent_id == agent.id).order_by(Source.name).all()
    jobs = db.query(AgentJob).filter(AgentJob.agent_id == agent.id).order_by(AgentJob.created_at.desc()).limit(10).all()
    base = _response(agent, _summaries([agent.id], db)[agent.id]).model_dump()
    return AgentAdminDetails(
        **base,
        sources=[AgentSourceSummary(id=source.id, name=source.name, root_path=source.root_path, next_scan_at=source.next_scan_at) for source in sources],
        recent_jobs=[AgentJobSummary(id=job.id, kind=job.kind, status=job.status, source_id=job.source_id, created_at=job.created_at, completed_at=job.completed_at, error=job.error) for job in jobs[:10]],
    )


def _get_agent(agent_id: str, db: Session) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.post(
    "/enrollments",
    response_model=AgentEnrollmentCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_enrollment(
    current_user: CurrentUser,
    feature_enabled: RemoteAgentsEnabled,
    db: Database,
):
    del feature_enabled
    code = create_enrollment_code()
    expires_at = _utcnow() + timedelta(minutes=15)
    db.add(
        AgentEnrollment(
            id=str(uuid.uuid4()),
            code_hash=hash_token(code),
            expires_at=expires_at,
            created_by_user_id=current_user.id,
        )
    )
    db.commit()
    return AgentEnrollmentCodeResponse(
        code=code,
        expires_at=expires_at.replace(tzinfo=timezone.utc),
    )


@router.get("", response_model=list[AgentAdminResponse])
async def list_agents(
    db: Database,
    current_user: CurrentUser,
):
    del current_user
    agents = db.query(Agent).order_by(Agent.created_at).all()
    summaries = _summaries([agent.id for agent in agents], db)
    return [_response(agent, summaries[agent.id]) for agent in agents]


@router.get("/{agent_id}", response_model=AgentAdminDetails)
async def get_agent(
    agent_id: str,
    db: Database,
    current_user: CurrentUser,
):
    del current_user
    return _detail_response(_get_agent(agent_id, db), db)


@router.patch("/{agent_id}", response_model=AgentAdminResponse)
async def update_agent(
    agent_id: str,
    update: AgentAdminUpdate,
    db: Database,
    current_user: CurrentUser,
):
    """Update the defaults inherited by future remote-source jobs."""
    del current_user
    agent = _get_agent(agent_id, db)
    agent.default_processing_mode = update.default_processing_mode
    db.commit()
    db.refresh(agent)
    return _response(agent, _summaries([agent.id], db)[agent.id])


@router.post("/{agent_id}/approve", response_model=AgentAdminResponse)
async def approve_agent(
    agent_id: str,
    db: Database,
    current_user: CurrentUser,
):
    del current_user
    agent = _get_agent(agent_id, db)
    if agent.status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is revoked")
    if agent.status in {"offline", "online"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agent is already approved"
        )
    now = _utcnow()
    agent.status = "offline"
    agent.approved_at = agent.approved_at or now
    agent.disabled_at = None
    db.commit()
    db.refresh(agent)
    return _response(agent, _summaries([agent.id], db)[agent.id])


@router.post("/{agent_id}/disable", response_model=AgentAdminResponse)
async def disable_agent(
    agent_id: str,
    db: Database,
    current_user: CurrentUser,
):
    del current_user
    agent = _get_agent(agent_id, db)
    if agent.status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is revoked")
    if agent.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agent is already disabled"
        )
    agent.status = "disabled"
    agent.disabled_at = _utcnow()
    db.commit()
    db.refresh(agent)
    return _response(agent, _summaries([agent.id], db)[agent.id])


@router.post("/{agent_id}/revoke", response_model=AgentAdminResponse)
async def revoke_agent(
    agent_id: str,
    db: Database,
    current_user: CurrentUser,
):
    del current_user
    agent = _get_agent(agent_id, db)
    if agent.status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is already revoked")
    agent.status = "revoked"
    agent.token_hash = None
    agent.disabled_at = _utcnow()
    db.commit()
    db.refresh(agent)
    return _response(agent, _summaries([agent.id], db)[agent.id])
