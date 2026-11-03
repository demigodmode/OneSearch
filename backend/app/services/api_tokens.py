# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Shape of API tokens: the prefix that tells them apart from session JWTs, and new secrets."""

import secrets

API_TOKEN_PREFIX = "os_"
# The start of the secret that is kept in the clear so people can tell tokens apart.
API_TOKEN_DISPLAY_LENGTH = len(API_TOKEN_PREFIX) + 4


def is_api_token(credential: str) -> bool:
    return credential.startswith(API_TOKEN_PREFIX)


def new_api_token_secret() -> str:
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
