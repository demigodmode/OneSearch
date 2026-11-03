# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authentication API endpoints
Handles user setup, login, logout, and session management
"""
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import time

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, update
import bcrypt
import jwt

from ..config import settings
from ..db.database import get_db
from ..models import ROLE_ADMIN, ApiToken, User, _utcnow
from ..schemas import (
    SetupRequest,
    LoginRequest,
    PasswordChangeRequest,
    UserResponse,
    AuthResponse,
    MessageResponse,
)
from ..services.agent_auth import hash_token
from ..services.api_tokens import is_api_token
from ..services.audit import AuditAction, AuditTarget, record_and_commit, record_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# JWT configuration
ALGORITHM = "HS256"
SESSION_PURPOSE = "session"
BCRYPT_ROUNDS = 12  # Cost factor for bcrypt
API_TOKEN_USE_WRITE_INTERVAL = timedelta(seconds=60)
TOKEN_SCOPE_ERROR = "API tokens can only be used for search"

# Rate limiting storage (in-memory, resets on restart)
rate_limit_store: dict[str, list[float]] = defaultdict(list)

# Bearer token security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_secret_key() -> str:
    """Get or generate session secret key"""
    if settings.session_secret:
        return settings.session_secret
    # Generate a temporary key if not configured (dev only)
    logger.warning("SESSION_SECRET not configured. Using temporary key (insecure for production)")
    return "temporary-dev-key-do-not-use-in-production"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def create_access_token(user_id: int, username: str, session_version: int) -> tuple[str, int]:
    """Create a JWT access token"""
    expire_hours = settings.session_expire_hours
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=expire_hours)
    expires_in = expire_hours * 3600  # seconds

    payload = {
        "sub": str(user_id),
        "username": username,
        "sv": session_version,
        "purpose": SESSION_PURPOSE,
        "exp": expire,
        "iat": now,
    }

    token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
    return token, expires_in


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except jwt.exceptions.InvalidTokenError:
        return None


def _is_session_payload(payload: dict[str, Any]) -> bool:
    """Tokens from before purposes existed have none and count as sessions."""
    return payload.get("purpose", SESSION_PURPOSE) == SESSION_PURPOSE


_last_prune = 0.0


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP from proxy headers.

    Checks X-Forwarded-For and X-Real-IP headers (set by nginx/reverse proxies)
    before falling back to request.client.host. Without this, all requests
    behind a proxy share the same rate limit bucket (127.0.0.1).
    """
    # X-Forwarded-For can contain a chain: "client, proxy1, proxy2"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # The leftmost IP is the original client
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"



def check_rate_limit(client_ip: str) -> bool:
    """Check if client has exceeded rate limit"""
    global _last_prune
    now = time.time()
    window = 60  # 1 minute window
    max_attempts = settings.auth_rate_limit

    # Periodically prune stale IPs (every 5 minutes)
    if now - _last_prune > 300:
        stale = [ip for ip, ts in rate_limit_store.items() if all(now - t >= window for t in ts)]
        for ip in stale:
            del rate_limit_store[ip]
        _last_prune = now

    # Clean old entries for this IP
    rate_limit_store[client_ip] = [
        t for t in rate_limit_store[client_ip] if now - t < window
    ]

    if len(rate_limit_store[client_ip]) >= max_attempts:
        return False

    rate_limit_store[client_ip].append(now)
    return True


def is_setup_required(db: Session) -> bool:
    """Check if initial setup is needed (no users exist)"""
    stmt = select(func.count()).select_from(User)
    count = db.execute(stmt).scalar()
    return count == 0


def ending_sessions_values() -> dict[str, Any]:
    """Values for an UPDATE that ends all of a user's sessions. Spread into .values()."""
    return {"session_version": User.session_version + 1}


def _session_is_current(payload: dict[str, Any], user: User) -> bool:
    """Tokens from before session versions existed have no sv and stay valid until they expire."""
    token_version = payload.get("sv")
    return token_version is None or token_version == user.session_version


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _record_api_token_use(token_id: int, now: datetime, db: Session) -> None:
    """Best effort. A busy database must not fail the request that carried the token."""
    # One conditional UPDATE, so concurrent requests write at most once per interval.
    try:
        result = db.execute(
            update(ApiToken)
            .where(
                ApiToken.id == token_id,
                or_(
                    ApiToken.last_used_at.is_(None),
                    ApiToken.last_used_at <= now - API_TOKEN_USE_WRITE_INTERVAL,
                ),
            )
            .values(last_used_at=now)
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.debug("Could not record use of API token %s", token_id, exc_info=True)
        return
    if result.rowcount == 0:
        logger.debug("API token %s last-used time not updated (used recently or deleted)", token_id)


def _user_from_api_token(credential: str, db: Session) -> User:
    token = db.execute(
        select(ApiToken).where(ApiToken.token_hash == hash_token(credential))
    ).scalar_one_or_none()
    if token is None:
        raise _unauthorized("Invalid API token")
    if token.revoked_at is not None:
        raise _unauthorized("API token revoked")

    now = _utcnow()
    if token.expires_at is not None and token.expires_at <= now:
        raise _unauthorized("API token expired")

    user = db.get(User, token.user_id)
    if not user or not user.is_active:
        raise _unauthorized("User not found or inactive")

    _record_api_token_use(token.id, now, db)
    return user


@dataclass(frozen=True)
class Caller:
    user: User
    via_token: bool


def _authenticate(credentials: HTTPAuthorizationCredentials | None, db: Session) -> Caller:
    """The one place that decides whether a request is a session or an API token."""
    if not credentials:
        raise _unauthorized("Not authenticated")

    if is_api_token(credentials.credentials):
        return Caller(user=_user_from_api_token(credentials.credentials, db), via_token=True)

    payload = decode_token(credentials.credentials)
    if not payload or not _is_session_payload(payload):
        raise _unauthorized("Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized("Invalid token payload")

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise _unauthorized("User not found or inactive")

    if not _session_is_current(payload, user):
        raise _unauthorized("Session expired")

    return Caller(user=user, via_token=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get the current user from a session.
    Raises 401 if not authenticated, and 403 if the caller used an API token.
    """
    caller = _authenticate(credentials, db)
    if caller.via_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TOKEN_SCOPE_ERROR)
    return caller.user


async def get_search_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),  # noqa: B008
    db: Session = Depends(get_db)  # noqa: B008
) -> User:
    """Dependency for the search-scope routes. Accepts a session or an API token."""
    return _authenticate(credentials, db).user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Dependency to get the current session user if authenticated, or None.
    Does not raise exceptions for unauthenticated requests. API tokens count as unauthenticated.
    """
    if not credentials:
        return None

    payload = decode_token(credentials.credentials)
    if not payload or not _is_session_payload(payload):
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = db.get(User, int(user_id))
    if not user or not user.is_active or not _session_is_current(payload, user):
        return None

    return user


def allow_anyone() -> None:
    """Marks a route that needs no sign-in. See access.py."""


async def require_user(user: User = Depends(get_current_user)) -> User:  # noqa: B008
    """Signed in, even while a password change is pending. Only for the routes that must stay reachable."""
    return user


def _password_is_current(user: User) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )
    return user


async def require_signed_in(user: User = Depends(require_user)) -> User:  # noqa: B008
    return _password_is_current(user)


async def require_search(user: User = Depends(get_search_user)) -> User:  # noqa: B008
    """Signed in with a session or an API token. Only for the search-scope routes."""
    return _password_is_current(user)


async def require_admin(user: User = Depends(require_signed_in)) -> User:  # noqa: B008
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


@router.get("/status", dependencies=[Depends(allow_anyone)])
async def auth_status(db: Session = Depends(get_db)):
    """
    Check authentication status and whether setup is required.

    Returns:
        setup_required: True if no users exist and initial setup is needed
    """
    return {
        "setup_required": is_setup_required(db)
    }


@router.post("/setup", response_model=AuthResponse, dependencies=[Depends(allow_anyone)])
async def setup_admin(
    request: Request,
    setup_data: SetupRequest,
    db: Session = Depends(get_db)
):
    """
    Initial setup endpoint to create the first admin user.

    This endpoint is only available when no users exist in the database.
    After the first user is created, this endpoint returns 403 Forbidden.

    Args:
        setup_data: Username and password for the admin account

    Returns:
        Access token for the newly created admin user

    Raises:
        403: Setup already completed (users exist)
        429: Rate limit exceeded
    """
    # Rate limiting
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later."
        )

    # Check if setup is still needed
    if not is_setup_required(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Use /api/auth/login instead."
        )

    # Check if username is already taken (shouldn't happen, but be safe)
    stmt = select(User).where(User.username == setup_data.username)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )

    # Create admin user
    user = User(
        username=setup_data.username,
        password_hash=hash_password(setup_data.password),
        is_active=True,
        role=ROLE_ADMIN,
    )

    db.add(user)
    db.flush()
    record_event(
        db,
        actor=user,
        action=AuditAction.SETUP_COMPLETED,
        target=AuditTarget.user(user.id, user.username),
        ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(user)

    logger.info(f"Admin user created: {user.username}")

    # Generate token
    token, expires_in = create_access_token(user.id, user.username, user.session_version)

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


def _record_failed_sign_in(
    db: Session,
    *,
    client_ip: str,
    target: AuditTarget,
    detail: dict[str, Any] | None = None,
) -> None:
    record_and_commit(
        db,
        actor=None,
        action=AuditAction.AUTH_LOGIN_FAILED,
        target=target,
        detail=detail,
        ip=client_ip,
    )


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(allow_anyone)])
async def login(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return access token.

    Args:
        login_data: Username and password

    Returns:
        Access token on successful authentication

    Raises:
        401: Invalid credentials
        429: Rate limit exceeded
    """
    # Rate limiting
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later."
        )

    # Find user by username
    stmt = select(User).where(User.username == login_data.username)
    user = db.execute(stmt).scalar_one_or_none()

    # Verify credentials (bcrypt uses constant-time comparison internally)
    if not user or not verify_password(login_data.password, user.password_hash):
        logger.warning(f"Failed login attempt for user: {login_data.username}")
        _record_failed_sign_in(
            db,
            client_ip=client_ip,
            target=AuditTarget.user(user.id if user else None, login_data.username),
        )
        raise _unauthorized("Invalid username or password")

    if not user.is_active:
        _record_failed_sign_in(
            db,
            client_ip=client_ip,
            target=AuditTarget.user(user.id, user.username),
            detail={"reason": "account disabled"},
        )
        raise _unauthorized("Account is disabled")

    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_event(db, actor=user, action=AuditAction.AUTH_LOGIN, ip=client_ip)
    db.commit()

    logger.info(f"User logged in: {user.username}")

    # Generate token
    token, expires_in = create_access_token(user.id, user.username, user.session_version)

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


@router.post("/change-password", response_model=AuthResponse)
async def change_password(
    request: Request,
    password_data: PasswordChangeRequest,
    current_user: User = Depends(require_user),  # noqa: B008
    db: Session = Depends(get_db),
) -> AuthResponse:
    """
    Change the signed-in user's password. Ends their other sessions.

    Returns a fresh access token so the current session stays signed in.

    Raises:
        400: Current password is wrong, or the new one is the same as the old
        409: Account changed while the request was running, try again
        429: Too many wrong current passwords from this user and IP
    """
    rate_limit_key = f"change-password:{current_user.id}:{get_client_ip(request)}"
    if not check_rate_limit(rate_limit_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later."
        )

    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if password_data.new_password == password_data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )

    expected_version = current_user.session_version
    result = db.execute(
        update(User)
        .where(User.id == current_user.id, User.session_version == expected_version)
        .values(
            password_hash=hash_password(password_data.new_password),
            must_change_password=False,
            **ending_sessions_values(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account changed. Sign in again and retry.",
        )
    record_event(
        db,
        actor=current_user,
        action=AuditAction.USER_PASSWORD_CHANGED,
        target=AuditTarget.user(current_user.id, current_user.username),
        ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(current_user)

    logger.info(f"Password changed: {current_user.username}")

    token, expires_in = create_access_token(
        current_user.id, current_user.username, current_user.session_version
    )

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(current_user: User = Depends(require_user)):  # noqa: B008
    """
    Logout the current user.

    Note: With JWT tokens, logout is primarily client-side (discard the token).
    This endpoint exists for API completeness and logging.

    Returns:
        Success message
    """
    logger.info(f"User logged out: {current_user.username}")
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(require_user)):  # noqa: B008
    """
    Get information about the currently authenticated user.

    Returns:
        User details (id, username, is_active, created_at)

    Raises:
        401: Not authenticated
    """
    return UserResponse.model_validate(current_user)
