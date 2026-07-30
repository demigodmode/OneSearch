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


def test_agent_image_is_non_root_without_network_ports_or_writable_roots():
    dockerfile = Path("agent/Dockerfile").read_text(encoding="utf-8")
    entrypoint = Path("agent/docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "python:3.13-slim" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]' in dockerfile
    assert 'VOLUME ["/var/lib/onesearch-agent"]' in dockerfile
    assert "useradd" in dockerfile
    assert "EXPOSE" not in dockerfile
    assert "PUID" in entrypoint and "PGID" in entrypoint
    assert "PUID must not be root" in entrypoint
    assert "PGID must not be root" in entrypoint
    assert 'exec gosu onesearch onesearch-agent "$@"' in entrypoint
    assert 'chown -R "$PUID:$PGID" /var/lib/onesearch-agent' in entrypoint
