# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
The audit log writer.

record_event queues an entry on the caller's session, so it commits with the change it describes.
Entries never fail the request: a bad entry is logged and the change goes ahead without it.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models import AuditEvent, User

logger = logging.getLogger(__name__)

COMMAND_LINE_ACTOR = "command line"
NAME_LIMIT = 50
DETAIL_LIMIT = 500


class AuditAction(StrEnum):
    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    USER_CREATED = "user.created"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_PASSWORD_CHANGED = "user.password_changed"
    USER_DISABLED = "user.disabled"
    USER_ENABLED = "user.enabled"
    USER_DELETED = "user.deleted"
    SETUP_COMPLETED = "setup.completed"


# A signed-in user, a plain name such as COMMAND_LINE_ACTOR, or None for nobody (failed sign-ins).
Actor = User | str | None


@dataclass(frozen=True)
class AuditTarget:
    type: str
    id: int | None
    label: str | None

    @classmethod
    def user(cls, user_id: int | None, username: str) -> "AuditTarget":
        return cls(type="user", id=user_id, label=username)


def action_clause(action: str):
    """Matches one action name, or every action under a prefix when it ends with a dot."""
    if action.endswith("."):
        return AuditEvent.action.startswith(action, autoescape=True)
    return AuditEvent.action == action


def _clip(value: str | None, column: str) -> str | None:
    """Cut a free-text value to its column. Text columns have no size, so they get NAME_LIMIT."""
    if value is None:
        return None
    return value[: AuditEvent.__table__.c[column].type.length or NAME_LIMIT]


def _detail_json(detail: dict[str, Any] | None) -> str | None:
    if detail is None:
        return None
    encoded = json.dumps(detail, default=str)
    if len(encoded) > DETAIL_LIMIT:
        logger.warning("Audit detail over %s characters, not stored", DETAIL_LIMIT)
        return None
    return encoded


def _queue_entry(db: Session, **fields: Any) -> None:
    db.add(AuditEvent(**fields))


def record_event(
    db: Session,
    *,
    actor: Actor,
    action: AuditAction,
    target: AuditTarget | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Queue an entry. It is written when the caller commits."""
    if isinstance(actor, User):
        actor_user_id, actor_username = actor.id, actor.username
    else:
        actor_user_id, actor_username = None, actor
    try:
        _queue_entry(
            db,
            actor_user_id=actor_user_id,
            actor_username=_clip(actor_username, "actor_username"),
            action=_clip(action, "action"),
            target_type=_clip(target.type, "target_type") if target else None,
            target_id=target.id if target else None,
            target_label=_clip(target.label, "target_label") if target else None,
            detail=_detail_json(detail),
            ip=_clip(ip, "ip"),
        )
    except Exception:
        logger.exception("Could not record audit event %s", action)


def record_and_commit(
    db: Session,
    *,
    actor: Actor,
    action: AuditAction,
    target: AuditTarget | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """For events with nothing else to commit, like a failed sign-in. A failed commit is logged."""
    record_event(db, actor=actor, action=action, target=target, detail=detail, ip=ip)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save audit event %s", action)
