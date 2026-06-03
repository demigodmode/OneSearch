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


def test_managed_alias_matches_default_mode():
    text = Path("docker-compose.managed-meili.yml").read_text()

    assert "Compatibility copy" in text
    assert "ONESEARCH_MANAGED_MEILI=true" in text
    assert "MEILI_URL=http://meilisearch:7700" not in text
    assert "onesearch_index:/app/meili_data" in text
