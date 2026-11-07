# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
API tokens: the prefix that tells them apart from session JWTs, new secrets, and the list and revoke
that both the owner's routes and the admin routes call.
"""

import secrets
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import ApiToken, _utcnow
from ..schemas import ApiTokenResponse, ApiTokenStatus

API_TOKEN_PREFIX = "os_"
# The start of the secret that is kept in the clear so people can tell tokens apart.
API_TOKEN_DISPLAY_LENGTH = len(API_TOKEN_PREFIX) + 4


def is_api_token(credential: str) -> bool:
    return credential.startswith(API_TOKEN_PREFIX)


def new_api_token_secret() -> str:
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def token_status(token: ApiToken, now: datetime) -> ApiTokenStatus:
    # Same order as the checks in _user_from_api_token, so a token that is both shows as revoked.
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= now:
        return "expired"
    return "active"


def api_token_response(token: ApiToken, now: datetime | None = None) -> ApiTokenResponse:
    return ApiTokenResponse(
        id=token.id,
        name=token.name,
        scope=token.scope,
        display_prefix=token.display_prefix,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked=token.revoked_at is not None,
        revoked_at=token.revoked_at,
        status=token_status(token, now or _utcnow()),
    )


def list_tokens_for_user(db: Session, user_id: int) -> list[ApiToken]:
    """Every token the user has, newest first. Revoked and expired ones are included."""
    stmt = select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.id.desc())
    return list(db.execute(stmt).scalars())


def revoke_token(db: Session, user_id: int, token_id: int) -> str | None:
    """
    Mark one active token that belongs to user_id as revoked.

    Returns the token's name, or None when there is no such active token.
    Does not commit. The caller commits with whatever else the request changes.
    """
    token = db.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id,
            ApiToken.revoked_at.is_(None),
        )
    )
    if token is None:
        return None
    name = token.name
    db.execute(update(ApiToken).where(ApiToken.id == token_id).values(revoked_at=_utcnow()))
    return name
