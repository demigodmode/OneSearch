# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for source path preflight diagnostics."""
import pytest
from fastapi import HTTPException

from app.api.sources import validate_root_path
from app.config import settings


def test_source_path_test_success_for_allowed_readable_directory(client, tmp_path):
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    try:
        response = client.post("/api/sources/test-path", json={"root_path": str(tmp_path)})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(tmp_path)
    assert data["exists"] is True
    assert data["is_directory"] is True
    assert data["readable"] is True
    assert data["inside_allowed_roots"] is True
    assert data["ok"] is True
    assert data["message"] == "Path is ready to use."


def test_source_path_test_rejects_windows_host_path_with_hint(client):
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = "/data"
    try:
        response = client.post("/api/sources/test-path", json={"root_path": "H:\\Docs"})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["looks_like_host_path"] is True
    assert data["inside_allowed_roots"] is False
    assert "container paths" in data["message"]
    assert "Allowed source roots: /data" == data["hint"]


def test_source_path_test_explains_likely_linux_host_path_outside_allowed_roots(client):
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = "/data"
    try:
        response = client.post("/api/sources/test-path", json={"root_path": "/mnt/nas/docs"})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["looks_like_host_path"] is True
    assert data["inside_allowed_roots"] is False
    assert data["message"] == "Root path is outside allowed source roots."
    assert data["hint"] == "Allowed source roots: /data"


def test_source_path_test_reports_missing_allowed_path(client, tmp_path):
    missing = tmp_path / "missing"
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    try:
        response = client.post("/api/sources/test-path", json={"root_path": str(missing)})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["exists"] is False
    assert data["inside_allowed_roots"] is True
    assert data["message"] == "Root path does not exist."


def test_source_path_test_reports_file_that_is_not_directory(client, tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    try:
        response = client.post("/api/sources/test-path", json={"root_path": str(file_path)})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["exists"] is True
    assert data["is_directory"] is False
    assert data["message"] == "Root path is not a directory."


def test_source_path_test_reports_unreadable_directory(client, tmp_path, monkeypatch):
    unreadable = tmp_path / "private"
    unreadable.mkdir()
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    monkeypatch.setattr("app.api.sources.os.access", lambda path, mode: False)
    try:
        response = client.post("/api/sources/test-path", json={"root_path": str(unreadable)})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["exists"] is True
    assert data["is_directory"] is True
    assert data["readable"] is False
    assert data["message"] == "Path exists but OneSearch cannot read it. Check Docker volume permissions or PUID/PGID."


def test_source_path_test_rejects_blank_path(client):
    response = client.post("/api/sources/test-path", json={"root_path": "   "})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["exists"] is False
    assert data["is_directory"] is False
    assert data["readable"] is False
    assert data["inside_allowed_roots"] is False
    assert data["message"] == "Root path is required."


def test_validate_root_path_rejects_blank_path():
    try:
        validate_root_path("   ")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "Root path is required"
    else:
        raise AssertionError("blank root path was accepted")


def test_source_path_test_rejects_symlink_escape(client, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = allowed / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available: {exc}")

    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(allowed)
    try:
        response = client.post("/api/sources/test-path", json={"root_path": str(link)})
    finally:
        settings.allowed_source_paths = original_allowed

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["inside_allowed_roots"] is False
    assert data["message"] == "Root path is outside allowed source roots."
