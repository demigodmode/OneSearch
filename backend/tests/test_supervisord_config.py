# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for container supervisor config rendering."""

from app.container.supervisord import render_supervisord_config


def test_managed_meili_config_starts_meilisearch_and_points_api_at_localhost():
    config = render_supervisord_config(managed_meili=True)

    assert "[program:meilisearch]" in config
    assert "command=/usr/local/bin/meilisearch --db-path /app/meili_data" in config
    assert "--master-key" not in config
    assert "MEILI_URL=\"http://127.0.0.1:7700\"" in config
    assert "MEILI_MASTER_KEY=\"%(ENV_MEILI_MASTER_KEY)s\"" in config
    assert "MEILI_ENV=\"production\"" in config
    assert "command=/app/start-backend.sh" in config


def test_external_meili_config_does_not_start_meilisearch():
    config = render_supervisord_config(managed_meili=False)

    assert "[program:meilisearch]" not in config
    assert "MEILI_URL=\"http://127.0.0.1:7700\"" not in config
