# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path


def test_default_compose_uses_managed_meili():
    text = Path("docker-compose.yml").read_text()

    assert "  meilisearch:" not in text
    assert "ONESEARCH_MANAGED_MEILI=true" in text
    assert "MEILI_URL=http://meilisearch:7700" not in text
    assert "onesearch_index:/app/meili_data" in text


def test_legacy_compose_keeps_two_container_mode():
    text = Path("docker-compose.legacy.yml").read_text()

    assert "  meilisearch:" in text
    assert "getmeili/meilisearch:v1.12" in text
    assert "MEILI_URL=http://meilisearch:7700" in text
    assert "ONESEARCH_MANAGED_MEILI=true" not in text
    # .env.example ships ONESEARCH_MANAGED_MEILI=true, and env_file would pass it through
    assert "ONESEARCH_MANAGED_MEILI=false" in text
    assert "MEILI_NO_ANALYTICS=true" in text


def test_compose_files_expose_runtime_uid_gid_defaults():
    for compose_file in [
        "docker-compose.yml",
        "docker-compose.legacy.yml",
    ]:
        text = Path(compose_file).read_text()

        assert "PUID=${PUID:-1000}" in text
        assert "PGID=${PGID:-1000}" in text


def test_compose_files_pull_the_published_image():
    # Users download a single compose file, so it can't depend on a local Dockerfile.
    for compose_file in [
        "docker-compose.yml",
        "docker-compose.legacy.yml",
    ]:
        lines = Path(compose_file).read_text().splitlines()

        assert "    image: ${ONESEARCH_IMAGE:-ghcr.io/demigodmode/onesearch:latest}" in lines
        assert not any(line.strip() == "build:" for line in lines)


def test_compose_files_pass_the_whole_env_file():
    for compose_file in ["docker-compose.yml", "docker-compose.legacy.yml"]:
        lines = Path(compose_file).read_text().splitlines()

        assert "    env_file: .env" in lines
