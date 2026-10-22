# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the public Docker startup smoke runner."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path("scripts/docker_smoke.py")


def smoke_module():
    spec = importlib.util.spec_from_file_location("docker_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identifiers_reject_ref_names_and_shell_metacharacters():
    smoke = smoke_module()
    assert smoke.validate_sha("a" * 40) == "a" * 40
    assert smoke.validate_run_id("12345-2") == "12345-2"
    for bad in ("main", "f" * 39, "g" * 40):
        with pytest.raises(ValueError):
            smoke.validate_sha(bad)
    for bad in ("../release", "run;echo", ""):
        with pytest.raises(ValueError):
            smoke.validate_run_id(bad)


def test_health_requires_healthy_backend_and_available_managed_meili():
    smoke = smoke_module()
    good = {"status": "healthy", "meilisearch": {"status": "available"}, "setup_required": True}
    assert smoke.health_ready(200, good)
    assert not smoke.health_ready(503, good)
    assert not smoke.health_ready(200, {**good, "status": "degraded"})
    assert not smoke.health_ready(200, {**good, "meilisearch": {"status": "unavailable"}})
    assert not smoke.health_ready(200, {**good, "setup_required": False})


def test_api_sequence_authenticates_indexes_and_checks_fixture_hit():
    smoke = smoke_module()
    calls = []

    def request(method, path, payload=None, auth=None, timeout=10):
        calls.append((method, path, payload, auth))
        responses = {
            "/api/auth/setup": (200, {"access_token": "setup-secret"}),
            "/api/auth/login": (200, {"access_token": "login-secret"}),
            "/api/sources": (201, {"id": "smoke-source", "root_path": "/smoke-fixture"}),
            "/api/sources/smoke-source/reindex": (200, {"stats": {"successful": 1, "failed": 0}}),
            "/api/search": (
                200,
                {"results": [{"source_id": "smoke-source", "path": "/smoke-fixture/fixture.txt"}]},
            ),
        }
        if path == "/api/search" and payload["q"] != "uniquequery":
            return 200, {"results": []}
        return responses[path]

    result = smoke.exercise_api(
        request,
        "smoke-admin",
        "password123",
        "fixture.txt",
        "uniquequery",
        alive=lambda: True,
        deadline_seconds=120,
        sleep=lambda _: None,
    )
    assert result["source_id"] == "smoke-source"
    assert [path for _, path, _, _ in calls] == [
        "/api/auth/setup",
        "/api/auth/login",
        "/api/sources",
        "/api/sources/smoke-source/reindex",
        "/api/search",
        "/api/search",
    ]
    assert calls[2][2]["root_path"] == "/smoke-fixture"
    assert calls[3][3] == "login-secret"
    assert calls[4][2]["q"] == "uniquequery"
    assert calls[4][3] == "login-secret"
    assert calls[5][2]["q"] != "uniquequery"
    assert calls[5][3] == "login-secret"


def test_api_sequence_rejects_wrong_source_or_missing_fixture_hit():
    smoke = smoke_module()

    def request(method, path, payload=None, auth=None, timeout=10):
        if path == "/api/auth/setup" or path == "/api/auth/login":
            return 200, {"access_token": "private"}
        if path == "/api/sources":
            return 201, {"id": "smoke-source", "root_path": "/smoke-fixture"}
        if path.endswith("/reindex"):
            return 200, {"stats": {"successful": 1, "failed": 0}}
        return 200, {"results": [{"source_id": "other", "path": "/wrong/fixture.txt"}]}

    with pytest.raises(smoke.SmokeError, match="search"):
        smoke.exercise_api(
            request,
            "smoke-admin",
            "password123",
            "fixture.txt",
            "uniquequery",
            alive=lambda: True,
            deadline_seconds=0.01,
            sleep=lambda _: None,
        )


def test_health_wait_fails_on_early_container_exit():
    smoke = smoke_module()
    with pytest.raises(smoke.SmokeError, match="exited"):
        smoke.wait_for_health(
            lambda *args, **kwargs: (503, {}),
            alive=lambda: False,
            deadline_seconds=10,
            sleep=lambda _: None,
        )


def test_cleanup_removes_only_recorded_resources_in_reverse_order():
    smoke = smoke_module()
    commands = []
    owner = smoke.OwnedDocker(lambda args, timeout=15: commands.append(args))
    owner.record("image", "onesearch-smoke:123")
    owner.record("network", "onesearch-smoke-123")
    owner.record("volume", "onesearch-smoke-123-data")
    owner.record("container", "onesearch-smoke-123-app")
    assert owner.cleanup() == []
    assert commands == [
        ["docker", "rm", "-f", "onesearch-smoke-123-app"],
        ["docker", "volume", "rm", "onesearch-smoke-123-data"],
        ["docker", "network", "rm", "onesearch-smoke-123"],
        ["docker", "image", "rm", "-f", "onesearch-smoke:123"],
    ]
    assert all("prune" not in command for args in commands for command in args)


def test_malformed_health_and_search_payloads_are_not_success():
    smoke = smoke_module()
    assert not smoke.health_ready(
        200, {"status": "healthy", "meilisearch": None, "setup_required": True}
    )
    assert not smoke.search_found({"results": None}, "source", "fixture.txt")
    assert not smoke.search_found({"results": [None, "garbage"]}, "source", "fixture.txt")


def test_docker_logs_include_stderr_without_unbounded_output(monkeypatch):
    smoke = smoke_module()

    class Result:
        returncode = 0
        stdout = "stdout log\n"
        stderr = "stderr log\n"

    monkeypatch.setattr(smoke.subprocess, "run", lambda *args, **kwargs: Result())
    assert smoke.docker_command(["docker", "logs", "--tail", "120", "owned"]) == (
        "stdout log\nstderr log"
    )


def test_cleanup_reports_failed_removal_and_attempts_remaining_resources():
    smoke = smoke_module()
    commands = []

    def command(args, timeout=15):
        commands.append(args)
        if args[1:3] == ["volume", "rm"]:
            raise smoke.SmokeError("remove failed")

    owner = smoke.OwnedDocker(command)
    owner.record("network", "owned-net")
    owner.record("volume", "owned-volume")
    errors = owner.cleanup()
    assert len(errors) == 1
    assert "owned-volume" in errors[0]
    assert commands[-1] == ["docker", "network", "rm", "owned-net"]


def test_container_environment_allows_only_the_fixture_path():
    smoke = smoke_module()
    values = smoke.container_environment("meili-secret", "session-secret")
    assert values["ONESEARCH_MANAGED_MEILI"] == "true"
    assert values["ALLOWED_SOURCE_PATHS"] == "/smoke-fixture"
    assert values["SCHEDULER_ENABLED"] == "false"
    assert values["MEILI_MASTER_KEY"] == "meili-secret"
    assert values["SESSION_SECRET"] == "session-secret"


def test_failed_docker_command_reports_bounded_redacted_daemon_error(monkeypatch):
    smoke = smoke_module()

    class Result:
        returncode = 125
        stdout = ""
        stderr = "daemon: invalid mount; key=meili-secret " + "x" * 3000

    monkeypatch.setattr(smoke.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(smoke.SmokeError) as failure:
        smoke.docker_command(["docker", "run", "-d"], redactions=("meili-secret",))
    message = str(failure.value)
    assert "invalid mount" in message
    assert "meili-secret" not in message
    assert "[redacted]" in message
    assert len(message) < 2300


def test_api_sequence_rejects_search_that_ignores_query():
    smoke = smoke_module()

    def request(method, path, payload=None, auth=None, timeout=10):
        if path in ("/api/auth/setup", "/api/auth/login"):
            return 200, {"access_token": "private"}
        if path == "/api/sources":
            return 201, {"id": "smoke-source", "root_path": "/smoke-fixture"}
        if path.endswith("/reindex"):
            return 200, {"stats": {"successful": 1, "failed": 0}}
        # Simulate a broken search implementation returning all documents for any query.
        return 200, {
            "results": [{"source_id": "smoke-source", "path": "/smoke-fixture/fixture.txt"}]
        }

    with pytest.raises(smoke.SmokeError, match="negative search"):
        smoke.exercise_api(
            request,
            "smoke-admin",
            "password123",
            "fixture.txt",
            "uniquequery",
            alive=lambda: True,
            deadline_seconds=120,
            sleep=lambda _: None,
        )


def test_failed_resource_creation_is_still_cleaned_up():
    smoke = smoke_module()
    commands = []

    def command(args, timeout=15):
        commands.append(args)
        if args[1:3] == ["network", "create"]:
            raise smoke.SmokeError("daemon failed after creating network")

    owner = smoke.OwnedDocker(command)
    with pytest.raises(smoke.SmokeError):
        owner.create("network", "owned-net", ["docker", "network", "create", "owned-net"])
    assert owner.cleanup() == []
    assert commands[-1] == ["docker", "network", "rm", "owned-net"]


def test_search_hit_with_invalid_path_does_not_crash():
    smoke = smoke_module()
    assert not smoke.search_found(
        {"results": [{"source_id": "source", "path": None}]},
        "source",
        "fixture.txt",
    )


def test_success_summary_records_step_timings_and_cleanup():
    smoke = smoke_module()
    lines = smoke.summary_lines(
        sha="a" * 40,
        image_id="sha256:123",
        step="setup, login, index and search",
        passed=True,
        elapsed=42.0,
        timings={"build": 30.0, "startup": 10.0, "api": 2.0},
        cleanup_errors=[],
    )
    joined = "\n".join(lines)
    assert "build 30.0s" in joined
    assert "startup 10.0s" in joined
    assert "api 2.0s" in joined
    assert "Cleanup: complete" in joined
    assert "health, setup, login, source, index, search" in joined
