# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
API tokens: the prefix that tells them apart from session JWTs, new secrets, and the list and revoke
that both the owner's routes and the admin routes call.
"""

import secrets

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import ApiToken, _utcnow
from ..schemas import ApiTokenResponse

API_TOKEN_PREFIX = "os_"
# The start of the secret that is kept in the clear so people can tell tokens apart.
API_TOKEN_DISPLAY_LENGTH = len(API_TOKEN_PREFIX) + 4


def is_api_token(credential: str) -> bool:
    return credential.startswith(API_TOKEN_PREFIX)


def new_api_token_secret() -> str:
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def api_token_response(token: ApiToken) -> ApiTokenResponse:
    return ApiTokenResponse(
        id=token.id,
        name=token.name,
        scope=token.scope,
        display_prefix=token.display_prefix,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked=token.revoked_at is not None,
    )


def list_active_tokens(db: Session, user_id: int) -> list[ApiToken]:
    """Newest first. Revoked tokens are left out."""
    stmt = (
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.id.desc())
    )
    return list(db.execute(stmt).scalars())


def revoke_token(db: Session, user_id: int, token_id: int) -> bool:
    """
    Mark one active token that belongs to user_id as revoked. Returns False when there is no such token.

    Does not commit. The caller commits with whatever else the request changes.
    """
    result = db.execute(
        update(ApiToken)
        .where(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id,
            ApiToken.revoked_at.is_(None),
        )
        .values(revoked_at=_utcnow())
    )
    return result.rowcount == 1
