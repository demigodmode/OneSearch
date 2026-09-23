# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for local source root listing and folder browsing endpoints."""
import re

import pytest

from app.config import settings


@pytest.fixture
def roots(tmp_path, monkeypatch):
    first = tmp_path / "data"
    second = tmp_path / "media"
    (first / "photos" / "2024").mkdir(parents=True)
    (first / "docs").mkdir()
    second.mkdir()
    monkeypatch.setattr(settings, "allowed_source_paths", f"{first},{second}")
    return first, second


def _root_id(client, path):
    body = client.get("/api/sources/local-roots").json()
    return next(root["root_id"] for root in body["roots"] if root["path"] == str(path).replace("\\", "/"))


def test_local_roots_lists_configured_roots(client, roots):
    response = client.get("/api/sources/local-roots")

    assert response.status_code == 200
    body = response.json()
    assert body["browse_available"] is True
    assert [root["path"] for root in body["roots"]] == [str(roots[0]), str(roots[1])]
    assert all(re.fullmatch(r"local-[0-9a-f]{12}", root["root_id"]) for root in body["roots"])


def test_root_ids_survive_reordering(client, roots, monkeypatch):
    before = _root_id(client, roots[1])
    monkeypatch.setattr(settings, "allowed_source_paths", f"{roots[1]},{roots[0]}")
    assert _root_id(client, roots[1]) == before


def test_removed_root_id_is_unknown(client, roots, monkeypatch):
    removed = _root_id(client, roots[1])
    monkeypatch.setattr(settings, "allowed_source_paths", str(roots[0]))

    response = client.post("/api/sources/browse-local", json={"root_id": removed, "path": ""})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "local_root_unknown"


def test_browse_lists_folders(client, roots):
    root_id = _root_id(client, roots[0])

    response = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": ""})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "root_id": root_id,
        "path": "",
        "entries": [{"name": "docs", "path": "docs"}, {"name": "photos", "path": "photos"}],
        "truncated": False,
    }


def test_browse_nested(client, roots):
    root_id = _root_id(client, roots[0])

    body = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": "photos"}).json()

    assert body["entries"] == [{"name": "2024", "path": "photos/2024"}]


@pytest.mark.parametrize("path", ["..", "photos/../..", "/etc", "photos\\2024", "a\x01b"])
def test_browse_rejects_invalid_paths(client, roots, path):
    root_id = _root_id(client, roots[0])

    response = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": path})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "browse_path_invalid"


def test_browse_missing_folder_is_unavailable_without_leaking_paths(client, roots):
    root_id = _root_id(client, roots[0])

    response = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": "nope"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "browse_path_unavailable"
    assert str(roots[0]) not in response.text


def test_browse_symlink_escape_is_unavailable(client, roots, tmp_path):
    outside = tmp_path / "outside"
    (outside / "secret").mkdir(parents=True)
    (roots[0] / "escape").symlink_to(outside, target_is_directory=True)
    root_id = _root_id(client, roots[0])

    listing = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": ""}).json()
    assert "escape" not in [entry["name"] for entry in listing["entries"]]

    response = client.post("/api/sources/browse-local", json={"root_id": root_id, "path": "escape"})
    assert response.status_code == 409


def test_empty_allowed_paths_disables_browsing(client, monkeypatch):
    monkeypatch.setattr(settings, "allowed_source_paths", "")

    assert client.get("/api/sources/local-roots").json() == {"browse_available": False, "roots": []}
    response = client.post("/api/sources/browse-local", json={"root_id": "local-000000000000", "path": ""})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "local_browse_unavailable"


def test_endpoints_require_auth(client, roots):
    client.headers.pop("Authorization", None)

    assert client.get("/api/sources/local-roots").status_code == 401
    assert client.post("/api/sources/browse-local", json={"root_id": "x", "path": ""}).status_code == 401
