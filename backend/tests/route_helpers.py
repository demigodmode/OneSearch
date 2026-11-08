# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Route listings by access level, for the tests that check who may call what."""

from fastapi.routing import APIRoute

from app.api.access import AccessLevel, access_level_of
from app.main import app


def api_routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def routes_at(*levels: AccessLevel) -> list[tuple[str, str]]:
    return [
        (method, route.path)
        for route in api_routes()
        if access_level_of(route) in levels
        for method in sorted(route.methods)
    ]
