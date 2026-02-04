# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for authentication API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base, User
from app.db.database import get_db
from app.api.auth import hash_password, verify_password, create_access_token, decode_token, rate_limit_store


# In-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def clear_rate_limit():
    """Clear rate limit store before each test"""
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


@pytest.fixture
def db_session():
    """Create test database session"""
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    """Create test client with database dependency override"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session):
    """Create a sample user in the database"""
    user = User(
        username="testuser",
        password_hash=hash_password("testpassword123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(sample_user):
    """Get authentication headers for sample user"""
    token, _ = create_access_token(sample_user.id, sample_user.username)
    return {"Authorization": f"Bearer {token}"}


class TestPasswordHashing:
    """Tests for password hashing utilities"""

    def test_hash_password(self):
        """Test password hashing produces different hash each time"""
        password = "testpassword123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Different salts
        assert hash1.startswith("$2b$")  # bcrypt format

    def test_verify_password_correct(self):
        """Test password verification with correct password"""
        password = "testpassword123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test password verification with incorrect password"""
        hashed = hash_password("correctpassword")

        assert verify_password("wrongpassword", hashed) is False


class TestJWTTokens:
    """Tests for JWT token utilities"""

    def test_create_access_token(self):
        """Test JWT token creation"""
        token, expires_in = create_access_token(1, "testuser")

        assert token is not None
        assert len(token) > 0
        assert expires_in > 0

    def test_decode_valid_token(self):
        """Test decoding a valid token"""
        token, _ = create_access_token(1, "testuser")
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["username"] == "testuser"

    def test_decode_invalid_token(self):
        """Test decoding an invalid token returns None"""
        payload = decode_token("invalid.token.here")

        assert payload is None


class TestAuthStatus:
    """Tests for /api/auth/status endpoint"""

    def test_auth_status_setup_required(self, client):
        """Test auth status when no users exist"""
        response = client.get("/api/auth/status")

        assert response.status_code == 200
        data = response.json()

        assert data["setup_required"] is True

    def test_auth_status_setup_complete(self, client, sample_user):
        """Test auth status when users exist"""
        response = client.get("/api/auth/status")

        assert response.status_code == 200
        data = response.json()

        assert data["setup_required"] is False


class TestSetupEndpoint:
    """Tests for /api/auth/setup endpoint"""

    def test_setup_success(self, client):
        """Test initial setup creates admin user"""
        setup_data = {
            "username": "admin",
            "password": "securepassword123"
        }

        response = client.post("/api/auth/setup", json=setup_data)

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_setup_forbidden_after_completion(self, client, sample_user):
        """Test setup is forbidden after first user exists"""
        setup_data = {
            "username": "admin2",
            "password": "anotherpassword123"
        }

        response = client.post("/api/auth/setup", json=setup_data)

        assert response.status_code == 403
        assert "already completed" in response.json()["detail"].lower()

    def test_setup_username_too_short(self, client):
        """Test setup validation for username length"""
        setup_data = {
            "username": "ab",  # Too short (min 3)
            "password": "securepassword123"
        }

        response = client.post("/api/auth/setup", json=setup_data)

        assert response.status_code == 422  # Validation error

    def test_setup_password_too_short(self, client):
        """Test setup validation for password length"""
        setup_data = {
            "username": "admin",
            "password": "short"  # Too short (min 8)
        }

        response = client.post("/api/auth/setup", json=setup_data)

        assert response.status_code == 422


class TestLoginEndpoint:
    """Tests for /api/auth/login endpoint"""

    def test_login_success(self, client, sample_user):
        """Test successful login returns token"""
        login_data = {
            "username": "testuser",
            "password": "testpassword123"
        }

        response = client.post("/api/auth/login", json=login_data)

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_invalid_username(self, client, sample_user):
        """Test login with wrong username fails"""
        login_data = {
            "username": "wronguser",
            "password": "testpassword123"
        }

        response = client.post("/api/auth/login", json=login_data)

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_login_invalid_password(self, client, sample_user):
        """Test login with wrong password fails"""
        login_data = {
            "username": "testuser",
            "password": "wrongpassword"
        }

        response = client.post("/api/auth/login", json=login_data)

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_login_inactive_user(self, client, db_session):
        """Test login with inactive user fails"""
        # Create inactive user
        user = User(
            username="inactiveuser",
            password_hash=hash_password("testpassword123"),
            is_active=False,
        )
        db_session.add(user)
        db_session.commit()

        login_data = {
            "username": "inactiveuser",
            "password": "testpassword123"
        }

        response = client.post("/api/auth/login", json=login_data)

        assert response.status_code == 401
        assert "disabled" in response.json()["detail"].lower()


class TestLogoutEndpoint:
    """Tests for /api/auth/logout endpoint"""

    def test_logout_success(self, client, auth_headers):
        """Test successful logout"""
        response = client.post("/api/auth/logout", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "logged out" in data["message"].lower()

    def test_logout_unauthorized(self, client):
        """Test logout without token fails"""
        response = client.post("/api/auth/logout")

        assert response.status_code == 401


class TestMeEndpoint:
    """Tests for /api/auth/me endpoint"""

    def test_get_current_user_success(self, client, sample_user, auth_headers):
        """Test getting current user info"""
        response = client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == sample_user.id
        assert data["username"] == sample_user.username
        assert data["is_active"] is True
        assert "created_at" in data

    def test_get_current_user_unauthorized(self, client):
        """Test getting user info without token fails"""
        response = client.get("/api/auth/me")

        assert response.status_code == 401

    def test_get_current_user_invalid_token(self, client):
        """Test getting user info with invalid token fails"""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = client.get("/api/auth/me", headers=headers)

        assert response.status_code == 401


class TestHealthWithSetupRequired:
    """Tests for setup_required in health endpoint"""

    def test_health_setup_required_true(self, client):
        """Test health endpoint shows setup_required when no users"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "setup_required" in data
        assert data["setup_required"] is True

    def test_health_setup_required_false(self, client, sample_user):
        """Test health endpoint shows setup_required=false when users exist"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "setup_required" in data
        assert data["setup_required"] is False
