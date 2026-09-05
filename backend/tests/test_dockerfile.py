# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for runtime Docker image dependencies."""

import base64
import os
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def test_runtime_image_installs_exiftool_for_raw_metadata():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "libimage-exiftool-perl" in dockerfile


def test_runtime_python_packages_are_not_editable_build_paths():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "uv pip install --system --no-editable" in dockerfile


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


def test_agent_image_build_without_a_key_leaves_updates_disabled(tmp_path):
    dockerfile = Path("agent/Dockerfile").read_text(encoding="utf-8")
    command = (
        'if [ -n "${AGENT_UPDATE_PUBLIC_KEY:-}" ]; then '
        'AGENT_UPDATE_PUBLIC_KEY="$AGENT_UPDATE_PUBLIC_KEY" python -c '
        "'import base64, os; key=base64.b64decode(os.environ[\"AGENT_UPDATE_PUBLIC_KEY\"], "
        "validate=True); assert len(key) == 32, \"public key must be raw 32 bytes\"' "
        '&& printf \'%s\\n\' "$AGENT_UPDATE_PUBLIC_KEY" > release_public_key.txt; fi'
    )

    assert command.replace(
        " > release_public_key.txt", " > /opt/onesearch/agent/onesearch_agent/release_public_key.txt"
    ) in dockerfile
    placeholder = "Replaced by agent-release.yml before packaging native release artifacts.\n"
    (tmp_path / "release_public_key.txt").write_text(placeholder, encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "AGENT_UPDATE_PUBLIC_KEY": ""},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (tmp_path / "release_public_key.txt").read_text(encoding="utf-8") == placeholder


def test_agent_image_build_key_is_explicitly_passed_to_python_and_rejects_bad_values(tmp_path):
    dockerfile = Path("agent/Dockerfile").read_text(encoding="utf-8")
    command = (
        'if [ -n "${AGENT_UPDATE_PUBLIC_KEY:-}" ]; then '
        'AGENT_UPDATE_PUBLIC_KEY="$AGENT_UPDATE_PUBLIC_KEY" python -c '
        "'import base64, os; key=base64.b64decode(os.environ[\"AGENT_UPDATE_PUBLIC_KEY\"], "
        "validate=True); assert len(key) == 32, \"public key must be raw 32 bytes\"' "
        '&& printf \'%s\\n\' "$AGENT_UPDATE_PUBLIC_KEY" > release_public_key.txt; fi'
    )
    key = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()

    assert command.replace(
        " > release_public_key.txt", " > /opt/onesearch/agent/onesearch_agent/release_public_key.txt"
    ) in dockerfile
    valid = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "AGENT_UPDATE_PUBLIC_KEY": key},
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0
    assert (tmp_path / "release_public_key.txt").read_text(encoding="utf-8") == key + "\n"

    for invalid in ("not-base64", base64.b64encode(b"short").decode()):
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=tmp_path,
            env={**os.environ, "AGENT_UPDATE_PUBLIC_KEY": invalid},
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
