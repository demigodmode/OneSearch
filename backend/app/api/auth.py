# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authentication API endpoints
Handles user setup, login, logout, and session management
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from collections import defaultdict
import time

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select, func
import bcrypt
import jwt

from ..db.database import get_db
from ..models import User
from ..schemas import (
    SetupRequest,
    LoginRequest,
    UserResponse,
    AuthResponse,
    MessageResponse,
)
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# JWT configuration
ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12  # Cost factor for bcrypt

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


def create_access_token(user_id: int, username: str) -> tuple[str, int]:
    """Create a JWT access token"""
    expire_hours = settings.session_expire_hours
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=expire_hours)
    expires_in = expire_hours * 3600  # seconds

    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": now,
    }

    token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
    return token, expires_in


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except jwt.exceptions.InvalidTokenError:
        return None


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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    Raises 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Dependency to get the current user if authenticated, or None.
    Does not raise exceptions for unauthenticated requests.
    """
    if not credentials:
        return None

    payload = decode_token(credentials.credentials)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        return None

    return user


@router.get("/status")
async def auth_status(db: Session = Depends(get_db)):
    """
    Check authentication status and whether setup is required.

    Returns:
        setup_required: True if no users exist and initial setup is needed
    """
    return {
        "setup_required": is_setup_required(db)
    }


@router.post("/setup", response_model=AuthResponse)
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
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Admin user created: {user.username}")

    # Generate token
    token, expires_in = create_access_token(user.id, user.username)

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


@router.post("/login", response_model=AuthResponse)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(f"User logged in: {user.username}")

    # Generate token
    token, expires_in = create_access_token(user.id, user.username)

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(current_user: User = Depends(get_current_user)):
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
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get information about the currently authenticated user.

    Returns:
        User details (id, username, is_active, created_at)

    Raises:
        401: Not authenticated
    """
    return UserResponse.model_validate(current_user)
