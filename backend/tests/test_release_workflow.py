# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Checks for the release workflow's runner cleanup."""
from pathlib import Path

WORKFLOW = Path(".github/workflows/docker-publish.yml")


def _step(text: str, name: str, next_name: str | None = None) -> str:
    start = text.index(f"      - name: {name}")
    if next_name is None:
        return text[start:]
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def test_release_reclaims_only_build_cache_before_buildx():
    text = WORKFLOW.read_text(encoding="utf-8")
    cleanup = _step(text, "Reclaim Docker build space", "Set up Docker Buildx")

    assert text.index("Reclaim Docker build space") < text.index("Set up Docker Buildx")
    assert "rm -rf /tmp/.buildx-cache /tmp/.buildx-cache-new" in cleanup
    assert "docker builder prune --all --force" in cleanup
    assert "docker system prune" not in cleanup
    assert "docker volume prune" not in cleanup


def test_release_cleans_incomplete_cache_even_after_failure():
    text = WORKFLOW.read_text(encoding="utf-8")
    cleanup = _step(text, "Clean up Docker build data")

    assert "if: always()" in cleanup
    assert "rm -rf /tmp/.buildx-cache-new" in cleanup
    assert "docker builder prune --all --force" in cleanup
