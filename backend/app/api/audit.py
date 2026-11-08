# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin read access to the audit log."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import AuditEvent, User
from ..schemas import AuditEventResponse, AuditPageResponse
from ..services.audit import action_clause
from .auth import require_admin

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _to_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        created_at=event.created_at,
        actor_user_id=event.actor_user_id,
        actor_username=event.actor_username,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        target_label=event.target_label,
        detail=event.detail_dict,
        ip=event.ip,
    )


@router.get("", response_model=AuditPageResponse)
async def list_audit_events(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[str | None, Query(max_length=50)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> AuditPageResponse:
    """
    Audit entries, newest first.

    `user` matches the actor or the target username. `action` is an exact name, or a prefix
    when it ends with a dot (`user.` for every user change). `before` is the id from the
    previous page's next_before.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc())
    if user:
        stmt = stmt.where(or_(AuditEvent.actor_username == user, AuditEvent.target_label == user))
    if action:
        stmt = stmt.where(action_clause(action))
    if before is not None:
        stmt = stmt.where(AuditEvent.id < before)

    # One extra row tells us whether another page exists.
    rows = list(db.execute(stmt.limit(limit + 1)).scalars())
    events = rows[:limit]
    next_before = events[-1].id if len(rows) > limit else None
    return AuditPageResponse(
        events=[_to_response(event) for event in events],
        next_before=next_before,
    )
