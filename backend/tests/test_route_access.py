# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Every API route has to say who may call it."""

import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from app.api.access import AccessLevel, access_level_of
from app.api.auth import get_current_user

from .route_helpers import api_routes, routes_at

SEARCH_SCOPE_ROUTES = {
    ("POST", "/api/search"),
    ("GET", "/api/documents/{document_id}"),
    ("GET", "/api/documents/{document_id}/preview"),
    ("POST", "/api/documents/{document_id}/download-link"),
}


def _find(method: str, path: str) -> APIRoute:
    for route in api_routes():
        if route.path == path and method in route.methods:
            return route
    raise AssertionError(f"no route {method} {path}")


def test_every_route_declares_an_access_level():
    missing = [
        f"{','.join(sorted(route.methods))} {route.path}"
        for route in api_routes()
        if access_level_of(route) is None
    ]
    assert missing == []


def test_route_without_a_level_is_reported():
    # Using get_current_user directly skips the access levels, so it doesn't count.
    scratch = FastAPI()

    @scratch.get("/bare")
    def bare():
        return {}

    @scratch.get("/raw-auth")
    def raw_auth(user=Depends(get_current_user)):  # noqa: B008
        return {}

    routes = {route.path: route for route in scratch.routes if isinstance(route, APIRoute)}
    assert access_level_of(routes["/bare"]) is None
    assert access_level_of(routes["/raw-auth"]) is None


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/health", AccessLevel.PUBLIC),
        ("POST", "/api/auth/login", AccessLevel.PUBLIC),
        ("POST", "/api/auth/setup", AccessLevel.PUBLIC),
        ("GET", "/api/documents/{document_id}/download", AccessLevel.PUBLIC),
        ("POST", "/api/agent/v1/enroll", AccessLevel.PUBLIC),
        ("GET", "/api/auth/me", AccessLevel.SIGNED_IN),
        ("POST", "/api/auth/logout", AccessLevel.SIGNED_IN),
        ("POST", "/api/auth/change-password", AccessLevel.SIGNED_IN),
        ("POST", "/api/auth/tokens", AccessLevel.SIGNED_IN),
        ("GET", "/api/auth/tokens", AccessLevel.SIGNED_IN),
        ("DELETE", "/api/auth/tokens/{token_id}", AccessLevel.SIGNED_IN),
        ("POST", "/api/search", AccessLevel.SEARCH),
        ("GET", "/api/documents/{document_id}", AccessLevel.SEARCH),
        ("GET", "/api/documents/{document_id}/preview", AccessLevel.SEARCH),
        ("POST", "/api/documents/{document_id}/download-link", AccessLevel.SEARCH),
        ("GET", "/api/sources", AccessLevel.SIGNED_IN),
        ("GET", "/api/settings", AccessLevel.SIGNED_IN),
        ("POST", "/api/sources", AccessLevel.ADMIN),
        ("PUT", "/api/settings", AccessLevel.ADMIN),
        ("GET", "/api/status", AccessLevel.ADMIN),
        ("GET", "/api/agents", AccessLevel.ADMIN),
        ("GET", "/api/users", AccessLevel.ADMIN),
        ("POST", "/api/users", AccessLevel.ADMIN),
        ("PATCH", "/api/users/{user_id}", AccessLevel.ADMIN),
        ("POST", "/api/users/{user_id}/reset-password", AccessLevel.ADMIN),
        ("DELETE", "/api/users/{user_id}", AccessLevel.ADMIN),
        ("POST", "/api/agent/v1/heartbeat", AccessLevel.AGENT),
        ("POST", "/api/agent/v1/jobs/claim", AccessLevel.AGENT),
    ],
)
def test_route_has_expected_access_level(method, path, expected):
    assert access_level_of(_find(method, path)) is expected


def test_search_scope_routes_are_exactly_the_four():
    assert set(routes_at(AccessLevel.SEARCH)) == SEARCH_SCOPE_ROUTES


def _token_refused_routes():
    return routes_at(AccessLevel.SIGNED_IN, AccessLevel.ADMIN)


@pytest.fixture
def search_token_headers(client):
    response = client.post("/api/auth/tokens", json={"name": "route sweep"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.mark.parametrize(("method", "path"), _token_refused_routes())
def test_api_token_is_refused_outside_search_scope(client, search_token_headers, method, path):
    response = client.request(method, re.sub(r"\{[^}]+\}", "dummy", path), headers=search_token_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "API tokens can only be used for search"


@pytest.mark.parametrize(("method", "path"), routes_at(AccessLevel.AGENT))
def test_api_token_is_not_an_agent_credential(client, search_token_headers, method, path):
    assert client.put("/api/settings", json={"remote_agents_enabled": True}).status_code == 200

    response = client.request(method, re.sub(r"\{[^}]+\}", "dummy", path), headers=search_token_headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid agent token"
