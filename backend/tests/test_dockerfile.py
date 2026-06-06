# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for runtime Docker image dependencies."""
from pathlib import Path


def test_runtime_image_installs_exiftool_for_raw_metadata():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "libimage-exiftool-perl" in dockerfile


def test_entrypoint_supports_runtime_puid_pgid_mapping():
    entrypoint = Path("entrypoint.sh").read_text(encoding="utf-8")

    assert "PUID" in entrypoint
    assert "PGID" in entrypoint
    assert "groupmod" in entrypoint
    assert "usermod" in entrypoint
    assert "su -s /bin/bash -p onesearch" in entrypoint
