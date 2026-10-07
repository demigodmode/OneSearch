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


def _container_env_names(compose_file):
    names = set()
    in_onesearch = False
    for line in Path(compose_file).read_text().splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
            in_onesearch = line.strip() == "onesearch:"
        entry = line.strip()
        if in_onesearch and entry.startswith("- ") and entry[2:3].isupper():
            names.add(entry[2:].split("=", 1)[0])
    return names


def test_every_backend_setting_can_be_set_from_the_compose_files():
    # A setting that isn't listed never reaches the container, so setting it in .env does nothing.
    from app.config import Settings

    settings = {name.upper() for name in Settings.model_fields}
    for compose_file in ["docker-compose.yml", "docker-compose.legacy.yml"]:
        names = _container_env_names(compose_file)
        # managed mode points the backend at its own Meilisearch
        expected = settings - {"MEILI_URL"} if compose_file == "docker-compose.yml" else settings

        assert expected - names == set(), compose_file


def test_compose_files_do_not_need_an_env_file():
    # env_file makes compose refuse to start without a physical .env
    for compose_file in ["docker-compose.yml", "docker-compose.legacy.yml"]:
        assert "env_file" not in Path(compose_file).read_text()
