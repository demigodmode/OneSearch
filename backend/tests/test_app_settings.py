# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for backend-managed app settings.
"""


def test_get_settings_returns_defaults(client):
    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "unsupported_file_policy": "metadata_only",
        "media_metadata_mode": "auto",
        "index_gps_metadata": False,
        "show_previews": True,
        "raw_preview_enabled": True,
        "max_preview_size_mb": 50,
        "media_probe_max_size_mb": 0,
        "image_metadata_max_size_mb": 100,
        "archive_extraction_max_size_mb": 100,
        "readable_preview_page_chars": 6000,
        "long_text_pagination_threshold_chars": 20000,
    }


def test_update_settings_persists_values(client):
    update = {
        "unsupported_file_policy": "skip",
        "media_metadata_mode": "off",
        "index_gps_metadata": True,
        "show_previews": False,
        "raw_preview_enabled": False,
        "max_preview_size_mb": 25,
        "media_probe_max_size_mb": 500,
        "image_metadata_max_size_mb": 250,
        "archive_extraction_max_size_mb": 250,
        "readable_preview_page_chars": 8000,
        "long_text_pagination_threshold_chars": 30000,
    }

    response = client.put("/api/settings", json=update)

    assert response.status_code == 200
    assert response.json() == update

    second_response = client.get("/api/settings")
    assert second_response.status_code == 200
    assert second_response.json() == update


def test_update_settings_accepts_partial_payload(client):
    response = client.put("/api/settings", json={"index_gps_metadata": True})

    assert response.status_code == 200
    body = response.json()
    assert body["index_gps_metadata"] is True
    assert body["unsupported_file_policy"] == "metadata_only"
    assert body["media_metadata_mode"] == "auto"
    assert body["show_previews"] is True
    assert body["raw_preview_enabled"] is True
    assert body["max_preview_size_mb"] == 50
    assert body["media_probe_max_size_mb"] == 0
    assert body["image_metadata_max_size_mb"] == 100
    assert body["archive_extraction_max_size_mb"] == 100
    assert body["readable_preview_page_chars"] == 6000
    assert body["long_text_pagination_threshold_chars"] == 20000


def test_update_settings_rejects_invalid_preview_size(client):
    response = client.put("/api/settings", json={"max_preview_size_mb": 10})

    assert response.status_code == 422


def test_update_settings_rejects_invalid_limit_values(client):
    for payload in [
        {"media_probe_max_size_mb": -1},
        {"image_metadata_max_size_mb": 0},
        {"archive_extraction_max_size_mb": 0},
        {"readable_preview_page_chars": 999},
        {"long_text_pagination_threshold_chars": 999},
    ]:
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 422


def test_settings_requires_auth(client):
    client.headers.pop("Authorization", None)

    response = client.get("/api/settings")

    assert response.status_code == 401
