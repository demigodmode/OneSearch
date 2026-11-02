# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

import re

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.access import AccessLevel, access_level_of
from app.api.auth import ALGORITHM, create_access_token, get_secret_key
from app.db.database import get_db
from app.main import app
from app.models import ROLE_ADMIN, ROLE_MEMBER, User


def _admin_routes():
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute) and access_level_of(route) is AccessLevel.ADMIN:
            for method in sorted(route.methods):
                routes.append((method, route.path))
    return routes


ADMIN_ROUTES = _admin_routes()


def _fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "dummy", path)


def test_there_are_admin_routes_to_check():
    assert len(ADMIN_ROUTES) > 10


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_member_gets_403_on_admin_route(member_client, method, path):
    response = member_client.request(method, _fill_path(path))

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_setup_creates_an_admin(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/auth/setup", json={"username": "owner", "password": "longenough"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    user = db_session.query(User).filter_by(username="owner").one()
    assert user.role == ROLE_ADMIN


def test_me_reports_admin_role(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["must_change_password"] is False


def test_me_reports_member_role(member_client):
    response = member_client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == ROLE_MEMBER


def test_member_can_search(member_client, monkeypatch):
    async def search(**_kwargs):
        return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 1}

    monkeypatch.setattr("app.api.search.meili_service.search", search)

    response = member_client.post("/api/search", json={"q": "invoice"})

    assert response.status_code == 200


def test_member_can_open_a_document(member_client, monkeypatch):
    async def get_document(document_id):
        return {
            "id": document_id,
            "source_id": "photos",
            "source_name": "Photos",
            "path": "/photos/a.txt",
            "basename": "a.txt",
            "extension": "txt",
            "type": "text",
            "size_bytes": 3,
            "modified_at": 1,
            "indexed_at": 1,
            "content": "abc",
            "title": None,
            "metadata": {},
        }

    monkeypatch.setattr("app.api.search.meili_service.get_document", get_document)

    response = member_client.get("/api/documents/photos--abc")

    assert response.status_code == 200
    assert response.json()["id"] == "photos--abc"


def test_member_reaches_preview_lookup(member_client, monkeypatch):
    async def missing_document(document_id):
        return None

    monkeypatch.setattr("app.api.preview.meili_service.get_document", missing_document)

    response = member_client.get("/api/documents/missing/preview")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"


def test_member_can_read_settings(member_client):
    response = member_client.get("/api/settings")

    assert response.status_code == 200


def test_member_sees_only_id_and_name_for_sources(member_client, sample_source):
    response = member_client.get("/api/sources")

    assert response.status_code == 200
    assert response.json() == [{"id": "test-source", "name": "Test Source"}]


def test_admin_sees_full_sources(client, sample_source):
    response = client.get("/api/sources")

    assert response.status_code == 200
    source = response.json()[0]
    assert source["root_path"] == sample_source.root_path
    assert "effective_schedule" in source
    assert "created_at" in source


def test_stale_session_version_is_rejected(client, db_session, test_user):
    user = test_user["user"]
    stale_token, _ = create_access_token(user.id, user.username, user.session_version)
    user.session_version += 1
    db_session.commit()

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale_token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired"


def test_current_session_version_is_accepted(client, db_session, test_user):
    user = test_user["user"]
    user.session_version = 3
    db_session.commit()
    token, _ = create_access_token(user.id, user.username, user.session_version)

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_token_without_session_version_still_works(client, test_user):
    user = test_user["user"]
    payload = {"sub": str(user.id), "username": user.username, "exp": 4102444800}
    token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_download_token_cannot_be_used_as_session(client, test_user):
    from app.api.preview import _create_download_token

    token = _create_download_token(test_user["user"].id, "photos--image123", test_user["user"].session_version)

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
