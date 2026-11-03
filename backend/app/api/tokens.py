# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
API token management for the signed-in user.

Tokens are checked on the search routes in auth.py. This module only creates and revokes them.
"""
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import ApiToken, ApiTokenScope, User, _utcnow
from ..schemas import ApiTokenCreatedResponse, ApiTokenCreateRequest, ApiTokenResponse
from ..services.agent_auth import hash_token
from ..services.api_tokens import (
    API_TOKEN_DISPLAY_LENGTH,
    api_token_response,
    list_active_tokens,
    new_api_token_secret,
    revoke_token,
)
from .auth import require_signed_in

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/tokens", response_model=list[ApiTokenResponse])
async def list_api_tokens(
    current_user: User = Depends(require_signed_in),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ApiTokenResponse]:
    """List your API tokens, newest first. Revoked tokens are left out."""
    return [api_token_response(token) for token in list_active_tokens(db, current_user.id)]


@router.post("/tokens", response_model=ApiTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_token(
    token_data: ApiTokenCreateRequest,
    current_user: User = Depends(require_signed_in),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ApiTokenCreatedResponse:
    """
    Create a search-scope API token. The secret is only returned here.

    Raises:
        403: Sent with an API token, or the password change is still pending
    """
    secret = new_api_token_secret()
    expires_at = None
    if token_data.expires_in_days is not None:
        expires_at = _utcnow() + timedelta(days=token_data.expires_in_days)

    token = ApiToken(
        user_id=current_user.id,
        name=token_data.name,
        scope=ApiTokenScope.SEARCH,
        token_hash=hash_token(secret),
        display_prefix=secret[:API_TOKEN_DISPLAY_LENGTH],
        created_at=_utcnow(),
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    logger.info(f"API token created: {token.display_prefix} by {current_user.username}")

    return ApiTokenCreatedResponse(**api_token_response(token).model_dump(), token=secret)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_token(
    token_id: int,
    current_user: User = Depends(require_signed_in),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    """
    Revoke one of your API tokens. It stops working straight away.

    Raises:
        404: No active token with that id belongs to you
    """
    if not revoke_token(db, current_user.id, token_id):
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
    db.commit()

    logger.info(f"API token revoked by {current_user.username}")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
