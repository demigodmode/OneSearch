# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Every API route has to say who may call it."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from app.api.access import AccessLevel, access_level_of
from app.api.auth import get_current_user
from app.main import app


def _api_routes():
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _find(method: str, path: str) -> APIRoute:
    for route in _api_routes():
        if route.path == path and method in route.methods:
            return route
    raise AssertionError(f"no route {method} {path}")


def test_every_route_declares_an_access_level():
    missing = [
        f"{','.join(sorted(route.methods))} {route.path}"
        for route in _api_routes()
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
        ("POST", "/api/search", AccessLevel.SIGNED_IN),
        ("GET", "/api/documents/{document_id}", AccessLevel.SIGNED_IN),
        ("GET", "/api/documents/{document_id}/preview", AccessLevel.SIGNED_IN),
        ("GET", "/api/sources", AccessLevel.SIGNED_IN),
        ("GET", "/api/settings", AccessLevel.SIGNED_IN),
        ("POST", "/api/sources", AccessLevel.ADMIN),
        ("PUT", "/api/settings", AccessLevel.ADMIN),
        ("GET", "/api/status", AccessLevel.ADMIN),
        ("GET", "/api/agents", AccessLevel.ADMIN),
        ("GET", "/api/users", AccessLevel.ADMIN),
        ("POST", "/api/users", AccessLevel.ADMIN),
        ("POST", "/api/agent/v1/heartbeat", AccessLevel.AGENT),
        ("POST", "/api/agent/v1/jobs/claim", AccessLevel.AGENT),
    ],
)
def test_route_has_expected_access_level(method, path, expected):
    assert access_level_of(_find(method, path)) is expected
