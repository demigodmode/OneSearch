# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("onesearch-backend")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
