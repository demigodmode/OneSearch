# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Secret creation and authentication dependencies for remote agents."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import case, update
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import Agent, AgentEnrollment
from .app_settings import AppSettingsService

_ENROLLMENT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
agent_bearer_scheme = HTTPBearer(auto_error=False)
Database = Annotated[Session, Depends(get_db)]
AgentCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(agent_bearer_scheme),
]


def hash_token(token: str) -> str:
    """Return the stable SHA-256 digest used for secret lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, expected_hash: str) -> bool:
    """Verify a raw secret without timing-sensitive string equality."""
    return hmac.compare_digest(hash_token(token), expected_hash)


def create_enrollment_code() -> str:
    """Create a human-readable one-time code using unambiguous characters."""
    value = "".join(secrets.choice(_ENROLLMENT_ALPHABET) for _ in range(8))
    return f"OS-{value[:4]}-{value[4:]}"


def create_agent_token() -> str:
    """Create a permanent high-entropy agent credential."""
    return secrets.token_urlsafe(32)


def consume_enrollment_code(db: Session, code: str) -> bool:
    """Atomically mark a currently valid enrollment code as used."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = db.execute(
        update(AgentEnrollment)
        .where(
            AgentEnrollment.code_hash == hash_token(code),
            AgentEnrollment.used_at.is_(None),
            AgentEnrollment.expires_at > now,
        )
        .values(used_at=now)
    )
    return result.rowcount == 1


def record_agent_heartbeat(
    db: Session,
    *,
    agent_id: str,
    version: str,
    platform: str,
    protocol_version: int | None = None,
) -> str | None:
    """Update heartbeat state only while the stored agent is still active."""
    result = db.execute(
        update(Agent)
        .where(
            Agent.id == agent_id,
            Agent.status.in_(("pending", "offline", "online")),
            Agent.token_hash.is_not(None),
        )
        .values(
            version=version,
            platform=platform,
            **({"protocol_version": protocol_version} if protocol_version is not None else {}),
            last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status=case((Agent.status == "offline", "online"), else_=Agent.status),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    return db.query(Agent.status).filter(Agent.id == agent_id).scalar()


AGENT_ONLINE_MAX_AGE = timedelta(seconds=120)


def agent_is_fresh(agent: Agent, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return agent.last_seen_at is not None and agent.last_seen_at >= now - AGENT_ONLINE_MAX_AGE


def mark_stale_agent_offline(db: Session, agent: Agent, *, now: datetime | None = None) -> bool:
    """Persist an offline transition only for a stale agent still marked online."""
    if agent.status != "online" or agent_is_fresh(agent, now=now):
        return False
    agent.status = "offline"
    db.flush()
    return True


def record_agent_activity(db: Session, agent_id: str) -> None:
    db.execute(
        update(Agent)
        .where(Agent.id == agent_id, Agent.status.in_(("offline", "online")))
        .values(
            last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status=case((Agent.status == "offline", "online"), else_=Agent.status),
        )
    )


def require_remote_agents_enabled(db: Database) -> None:
    """Reject protocol operations while remote agents are globally disabled."""
    if not AppSettingsService(db).get_settings().remote_agents_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Remote agents are disabled",
        )


async def get_authenticated_agent(
    credentials: AgentCredentials,
    db: Database,
) -> Agent:
    """Authenticate a remote agent bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hash_token(credentials.credentials)
    agent = db.query(Agent).filter(Agent.token_hash == token_hash).one_or_none()
    if (
        agent is None
        or agent.token_hash is None
        or not verify_token(credentials.credentials, agent.token_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if agent.status in {"disabled", "revoked"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active")
    return agent


async def require_approved_agent(
    agent: Annotated[Agent, Depends(get_authenticated_agent)],
) -> Agent:
    """Restrict protocol operations to approved agents."""
    if agent.status not in {"offline", "online"} or agent.approved_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent is not approved",
        )
    return agent
