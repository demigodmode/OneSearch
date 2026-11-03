# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin APIs for managing user accounts."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from ..db.database import get_db
from ..db.locks import begin_immediate
from ..models import ROLE_ADMIN, AgentEnrollment, ApiToken, SourceBatch, User
from ..schemas import (
    ApiTokenResponse,
    UserAdminResponse,
    UserCreateRequest,
    UserPasswordResetRequest,
    UserUpdateRequest,
)
from ..services.api_tokens import api_token_response, list_active_tokens, revoke_token
from ..services.audit import AuditAction, AuditTarget, record_event
from .auth import ending_sessions_values, hash_password, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


def _username_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Username already exists",
    )


def _user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _busy_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Someone else is changing users right now. Try again.",
    )


def _last_admin_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="There has to be at least one active admin",
    )


def _active_admins_lock_statement() -> Select:
    return (
        select(User.id)
        .where(User.role == ROLE_ADMIN, User.is_active.is_(True))
        .order_by(User.id)
        .with_for_update()
    )


def _active_admin_ids_locked(db: Session) -> list[int]:
    # SQLite has no row locks, so take the database write lock first. Postgres
    # locks the admin rows in the SELECT itself. Either way it holds until commit.
    if db.get_bind().dialect.name == "sqlite":
        db.rollback()
        try:
            begin_immediate(db)
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            raise _busy_error() from exc
    return list(db.execute(_active_admins_lock_statement()).scalars())


def _guard_admin_removal(admin: User, user: User, active_admin_ids: list[int]) -> None:
    if user.id == admin.id:
        raise _not_yourself_error()
    if user.id in active_admin_ids and len(active_admin_ids) == 1:
        raise _last_admin_error()


def _not_yourself_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="You can't do that to your own account",
    )


def _created_by_name(db: Session, user: User) -> str | None:
    if user.created_by_id is None:
        return None
    creator = db.get(User, user.created_by_id)
    return creator.username if creator else None


def _to_admin_response(user: User, created_by: str | None) -> UserAdminResponse:
    return UserAdminResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        created_by=created_by,
        last_login_at=user.last_login_at,
    )


@router.get("", response_model=list[UserAdminResponse])
async def list_users(
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[UserAdminResponse]:
    """List every user, ordered by username."""
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    usernames = {user.id: user.username for user in users}
    return [_to_admin_response(user, usernames.get(user.created_by_id)) for user in users]


@router.post("", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserAdminResponse:
    """
    Create a user with a temporary password. They must change it before anything else.

    Raises:
        409: Username already exists
    """
    existing = db.execute(select(User.id).where(User.username == user_data.username)).first()
    if existing:
        raise _username_taken()

    user = User(
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        is_active=True,
        role=user_data.role,
        must_change_password=True,
        created_by_id=admin.id,
    )
    db.add(user)
    try:
        db.flush()
        record_event(
            db,
            actor=admin,
            action=AuditAction.USER_CREATED,
            target=AuditTarget.user(user.id, user.username),
            detail={"role": user.role},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _username_taken() from None
    db.refresh(user)

    logger.info(f"User created: {user.username} by {admin.username}")

    return _to_admin_response(user, admin.username)


@router.patch("/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: int,
    update_data: UserUpdateRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserAdminResponse:
    """
    Change a user's role or turn their account on or off.
    A role change or a disable ends their sessions.

    Raises:
        400: Trying to disable or demote your own account
        404: Unknown user
        409: The user is the last active admin, or another admin change is in progress
    """
    active_admin_ids = _active_admin_ids_locked(db)
    user = _user_or_404(db, user_id)
    changes = update_data.model_dump(exclude_none=True)
    old_role = user.role
    new_role = changes.get("role", user.role)
    was_active = user.is_active
    new_active = changes.get("is_active", user.is_active)
    role_changed = new_role != old_role
    disabled_now = user.is_active and not new_active

    if user.is_active and user.is_admin and (new_role != ROLE_ADMIN or not new_active):
        _guard_admin_removal(admin, user, active_admin_ids)

    if role_changed or disabled_now:
        changes.update(ending_sessions_values())
    if changes:
        db.execute(update(User).where(User.id == user.id).values(**changes))
    target = AuditTarget.user(user.id, user.username)
    if role_changed:
        record_event(
            db,
            actor=admin,
            action=AuditAction.USER_ROLE_CHANGED,
            target=target,
            detail={"old": old_role, "new": new_role},
        )
    if new_active != was_active:
        record_event(
            db,
            actor=admin,
            action=AuditAction.USER_ENABLED if new_active else AuditAction.USER_DISABLED,
            target=target,
        )
    db.commit()
    db.refresh(user)

    logger.info(f"User updated: {user.username} by {admin.username}")

    return _to_admin_response(user, _created_by_name(db, user))


@router.post("/{user_id}/reset-password", response_model=UserAdminResponse)
async def reset_user_password(
    user_id: int,
    reset_data: UserPasswordResetRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserAdminResponse:
    """
    Set a new temporary password. The user must change it at next sign-in and their sessions end.

    Raises:
        404: Unknown user
    """
    user = _user_or_404(db, user_id)
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            password_hash=hash_password(reset_data.password),
            must_change_password=True,
            **ending_sessions_values(),
        )
    )
    record_event(
        db,
        actor=admin,
        action=AuditAction.USER_PASSWORD_RESET,
        target=AuditTarget.user(user.id, user.username),
    )
    db.commit()
    db.refresh(user)

    logger.info(f"Password reset: {user.username} by {admin.username}")

    return _to_admin_response(user, _created_by_name(db, user))


@router.get("/{user_id}/tokens", response_model=list[ApiTokenResponse])
async def list_user_tokens(
    user_id: int,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ApiTokenResponse]:
    """List a user's API tokens, newest first. Revoked tokens are left out and secrets are never shown.

    Raises:
        404: Unknown user
    """
    _user_or_404(db, user_id)
    return [api_token_response(token) for token in list_active_tokens(db, user_id)]


@router.delete("/{user_id}/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_token(
    user_id: int,
    token_id: int,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    """
    Revoke one of a user's API tokens. It stops working straight away.

    Raises:
        404: No active token with that id belongs to the user
    """
    if not revoke_token(db, user_id, token_id):
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
    db.commit()

    logger.info(f"API token revoked: user {user_id} by {admin.username}")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    """
    Delete a user. Disabling is the normal way to remove someone; this is for mistakes.

    Raises:
        400: Trying to delete your own account
        404: Unknown user
        409: The user is the last active admin, or another admin change is in progress
    """
    active_admin_ids = _active_admin_ids_locked(db)
    user = _user_or_404(db, user_id)
    _guard_admin_removal(admin, user, active_admin_ids)
    target = AuditTarget.user(user.id, user.username)

    db.execute(delete(AgentEnrollment).where(AgentEnrollment.created_by_user_id == user.id))
    db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
    db.execute(update(User).where(User.created_by_id == user.id).values(created_by_id=None))
    db.delete(user)
    # The before_delete hook on User reads the batches it owns, so flush before clearing the owner.
    db.flush()
    db.execute(
        update(SourceBatch).where(SourceBatch.owner_user_id == user.id).values(owner_user_id=None)
    )
    record_event(db, actor=admin, action=AuditAction.USER_DELETED, target=target)
    db.commit()

    logger.info(f"User deleted: {user.username} by {admin.username}")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
