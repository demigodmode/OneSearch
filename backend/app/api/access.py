# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Who may call a route.

Every API route declares one access level through the dependency it uses:

- ``dependencies=[Depends(allow_anyone)]`` for routes anyone can call
- ``require_signed_in`` for anything a signed-in user may do
- ``require_admin`` for changing how OneSearch is set up
- ``get_authenticated_agent`` from ``services.agent_auth`` for the agent protocol

The dependencies themselves live in ``auth.py`` so routes there can use them too.

``tests/test_route_access.py`` fails for a route that declares none of these.
"""

from collections.abc import Callable
from enum import Enum
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from ..services.agent_auth import get_authenticated_agent
from .auth import allow_anyone, require_admin, require_signed_in


class AccessLevel(Enum):
    PUBLIC = "public"
    SIGNED_IN = "signed_in"
    ADMIN = "admin"
    AGENT = "agent"


# Checked in this order, so a route that pulls in several gets the strictest.
_LEVELS = (
    (require_admin, AccessLevel.ADMIN),
    (require_signed_in, AccessLevel.SIGNED_IN),
    (get_authenticated_agent, AccessLevel.AGENT),
    (allow_anyone, AccessLevel.PUBLIC),
)


def _dependency_calls(dependant: Dependant) -> set[Callable[..., Any]]:
    calls: set[Callable[..., Any]] = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _dependency_calls(sub)
    return calls


def access_level_of(route: APIRoute) -> AccessLevel | None:
    calls = _dependency_calls(route.dependant)
    for dependency, level in _LEVELS:
        if dependency in calls:
            return level
    return None
