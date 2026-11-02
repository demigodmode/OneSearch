# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin APIs for managing user accounts."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import User
from ..schemas import UserAdminResponse, UserCreateRequest
from .auth import hash_password, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


def _username_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Username already exists",
    )


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
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _username_taken() from None
    db.refresh(user)

    logger.info(f"User created: {user.username} by {admin.username}")

    return _to_admin_response(user, admin.username)
