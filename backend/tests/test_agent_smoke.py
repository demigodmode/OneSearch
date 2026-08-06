"""Release-harness contract tests with all external effects injected."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def smoke_module():
    path = Path(__file__).parents[2] / "scripts" / "agent_smoke.py"
    spec = importlib.util.spec_from_file_location("agent_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def command_templates() -> dict[str, str]:
    return {
        name: json.dumps(["release-hook", name, "{server_url}"])
        for name in {
            "enroll",
            "start",
            "stop",
            "rename_fixture",
            "delete_fixture",
            "restore_fixture",
            "update_check",
            "state_probe",
            "previous_install",
            "previous_start",
            "previous_stop",
            "current_install",
            "heartbeat_probe",
            "cleanup_processes",
        }
    }


def config(smoke, **overrides):
    values = {
        "url": "https://server",
        "admin_token": "admin-secret",
        "agent_name": "smoke-agent",
        "fixture_agent_path": "/fixtures/agent",
        "fixture_server_path": "/fixtures/server",
        "commands": command_templates(),
        "previous_version": "1.0.0",
        "current_version": "2.0.0",
        "notification_regex": "2[.]0[.]0 is available",
        "original_marker": "copper-jupiter",
        "renamed_marker": "violet-saturn",
        "poll_attempts": 3,
        "poll_seconds": 0,
        "due_intervals": 2,
        "schedule_interval_seconds": 1,
        "offline_grace_seconds": 2,
    }
    values.update(overrides)
    return smoke.SmokeConfig(**values)


class Scenario:
    """Strict fake for a complete two-machine release-gate conversation."""

    def __init__(self, smoke):
        self.smoke = smoke
        self.agent_id = "agent-1"
        self.status = "absent"
        self.version = "2.0.0"
        self.agent_started = False
        self.source_ids: list[str] = []
        self.jobs: list[dict] = []
        self.documents = {
            "source-agent": {"id": "doc-agent", "marker": "copper-jupiter"},
            "source-server": {"id": "doc-server", "marker": "copper-jupiter"},
        }
        self.calls: list[tuple[str, str]] = []
        self.commands: list[str] = []
        self.phases_seen: set[str] = set()
        self.enrollment_code = "one-time-secret"
        self.enrollment_stdin: str | None = None
        self.catch_up_created = False
        self.catch_up_reads = 0
        self.revoked = False
        self.cleanup_started = False
        self.clock = 0.0
        self.source_reads = 0

    def _agent(self):
        return {
            "id": self.agent_id,
            "name": "smoke-agent",
            "status": self.status,
            "version": self.version,
            "config_fingerprint": "config-sha256",
            "recent_jobs": list(reversed(self.jobs[-10:])),
        }

    def _job(self, kind="scan", source_id=None, reason=None):
        job = {
            "id": f"job-{len(self.jobs) + 1}",
            "kind": kind,
            "source_id": source_id,
            "reason": reason,
            "status": "completed",
        }
        self.jobs.append(job)
        return job

    def request(self, method, path, body=None, headers=None):
        del headers
        self.calls.append((method, path))
        reply = self.smoke.Reply
        if self.revoked and method != "DELETE" and not self.cleanup_started:
            raise AssertionError(f"functional HTTP request after revocation: {method} {path}")
        if (method, path) == ("POST", "/api/agents/enrollments"):
            assert self.status == "absent"
            self.phases_seen.add("enrollment")
            return reply(201, {"code": self.enrollment_code})
        if (method, path) == ("GET", "/api/agents"):
            assert self.status == "pending"
            self.phases_seen.add("enrollment_pending")
            return reply(200, [self._agent()])
        if (method, path) == ("POST", "/api/agents/agent-1/approve"):
            assert self.status == "pending"
            self.status = "offline"
            self.phases_seen.add("approved_offline")
            return reply(200, self._agent())
        if (method, path) == ("GET", "/api/agents/agent-1"):
            agent = self._agent()
            pending = [job for job in self.jobs if job["status"] == "pending"]
            if self.catch_up_created and pending:
                self.catch_up_reads += 1
                if self.catch_up_reads > 1:
                    pending[0]["status"] = "completed"
                    agent = self._agent()
            return reply(200, agent)
        if (method, path) == ("POST", "/api/sources/test-path"):
            assert self.status == "online" and not self.source_ids
            assert body == {
                "root_path": "/fixtures/agent",
                "location_type": "agent",
                "agent_id": "agent-1",
            }
            self.phases_seen.add("remote_browse")
            return reply(200, {"job_id": self._job("browse")["id"], "status": "pending"})
        if (method, path) == ("POST", "/api/sources"):
            assert "remote_browse" in self.phases_seen
            assert body["location_type"] == "agent" and body["agent_id"] == "agent-1"
            source_id = "source-agent" if body["processing_mode"] == "on_agent" else "source-server"
            assert source_id not in self.source_ids
            self.source_ids.append(source_id)
            if source_id == "source-agent":
                assert body["use_default_schedule"] is True
                schedule = {
                    "schedule_type": "cron",
                    "scan_schedule": "@daily",
                    "interval_value": None,
                    "interval_unit": None,
                }
                self.phases_seen.add("global_schedule")
            else:
                assert body["use_default_schedule"] is False
                assert body["schedule_type"] == "interval"
                schedule = {
                    "schedule_type": "interval",
                    "scan_schedule": None,
                    "interval_value": 1,
                    "interval_unit": "minutes",
                }
                self.phases_seen.add("source_schedule")
            return reply(
                201,
                {
                    "id": source_id,
                    **body,
                    "effective_schedule": schedule,
                },
            )
        if method == "GET" and path in {"/api/sources/source-agent", "/api/sources/source-server"}:
            self.source_reads += 1
            source_id = path.rsplit("/", 1)[1]
            mode = "on_agent" if source_id == "source-agent" else "on_server"
            return reply(
                200,
                {
                    "id": source_id,
                    "root_path": "/fixtures/agent" if mode == "on_agent" else "/fixtures/server",
                    "agent_id": "agent-1",
                    "processing_mode": mode,
                    "use_default_schedule": mode == "on_agent",
                    "next_scan_at": self.source_reads,
                },
            )
        if method == "POST" and path.endswith("/reindex"):
            source_id = path.split("/")[3]
            assert len(self.source_ids) == 2 and source_id in self.source_ids
            assert self.status == "online"
            self.phases_seen.add(
                "scan_" + ("on_agent" if source_id == "source-agent" else "on_server")
            )
            return reply(202, {"job_id": self._job("scan", source_id)["id"]})
        if (method, path) == ("POST", "/api/search"):
            marker = body["q"]
            source_ids = [body["source_id"]] if body.get("source_id") else list(self.source_ids)
            results = [
                {"id": self.documents[source_id]["id"]}
                for source_id in source_ids
                if self.documents.get(source_id, {}).get("marker") == marker
            ]
            if body.get("source_id") == "source-agent" and marker == "violet-saturn" and results:
                self.phases_seen.add("rename_reconciled")
            if (
                body.get("source_id") == "source-agent"
                and marker == "copper-jupiter"
                and self.documents["source-agent"]["marker"] == "violet-saturn"
                and not results
            ):
                self.phases_seen.add("rename_removed_original")
            if (
                body.get("source_id") == "source-server"
                and "source-server" not in self.documents
                and not results
            ):
                self.phases_seen.add("deletion_reconciled")
            self.phases_seen.add("offline_search" if self.status == "offline" else "search")
            return reply(200, {"results": results, "total": len(results)})
        if method == "GET" and path.startswith("/api/documents/") and path.endswith("/preview"):
            assert self.status == "online"
            self.phases_seen.add("preview")
            return reply(200, b"preview")
        if method == "GET" and path.startswith("/api/documents/") and "/download?" not in path:
            self.phases_seen.add("offline_detail" if self.status == "offline" else "detail")
            return reply(200, {"id": path.rsplit("/", 1)[1], "content": "indexed text"})
        if method == "POST" and path.endswith("/download-link"):
            if self.status == "offline":
                self.phases_seen.add("offline_download_rejected")
                return reply(409, {"detail": "agent offline"})
            self.phases_seen.add("download_link")
            return reply(200, {"url": "/api/documents/doc-agent/download?token=download-secret"})
        if method == "GET" and path.startswith("/api/documents/doc-agent/download?"):
            if self.status == "offline":
                raise AssertionError(
                    "expired signed URL must not stand in for an offline download check"
                )
            self.phases_seen.add("download")
            return reply(200, b"original")
        if method == "DELETE" and path.startswith("/api/sources/"):
            self.cleanup_started = True
            return reply(204)
        if (method, path) == ("POST", "/api/agents/agent-1/revoke"):
            assert "current_install" in self.phases_seen
            self.revoked = True
            self.status = "revoked"
            self.phases_seen.add("revocation")
            return reply(200, self._agent())
        raise AssertionError(f"unexpected request: {method} {path} {body!r}")

    def run(self, argv, *, stdin=None, env=None):
        name = argv[1]
        assert argv == ["release-hook", name, "https://server"]
        self.commands.append(name)
        reply = self.smoke.Reply
        if name == "enroll":
            assert stdin == self.enrollment_code
            assert env == {"ONESEARCH_ENROLLMENT_CODE": self.enrollment_code}
            assert self.enrollment_code not in argv
            self.enrollment_stdin = stdin
            self.status = "pending"
            return reply(0, {"agent_id": self.agent_id})
        assert stdin is None and env is None
        if name in {"start", "previous_start"}:
            assert self.status != "revoked"
            self.status = "online"
            self.version = "1.0.0" if name == "previous_start" else "2.0.0"
            self.agent_started = True
            if (
                name == "start"
                and "delete_fixture" in self.commands
                and "update_check" not in self.commands
            ):
                self.phases_seen.add("reconnect")
            if name == "start" and self.status == "online":
                self.phases_seen.add("agent_online")
            return reply(0, {"agent_id": self.agent_id, "version": self.version})
        if name in {"stop", "previous_stop"}:
            if self.status != "revoked":
                self.status = "offline"
            self.agent_started = False
            return reply(0, {})
        if name == "rename_fixture":
            assert self.catch_up_created
            self.documents["source-agent"]["marker"] = "violet-saturn"
            return reply(0, {})
        if name == "delete_fixture":
            self.documents.pop("source-server")
            return reply(0, {})
        if name == "restore_fixture":
            return reply(0, {})
        if name == "update_check":
            assert "scan_on_agent" in self.phases_seen and "scan_on_server" in self.phases_seen
            self.phases_seen.add("signed_update")
            return reply(
                0,
                {
                    "message": "2.0.0 is available",
                    "signature_verified": True,
                    "update_available": True,
                    "install_type": "docker",
                    "self_replaced": False,
                },
            )
        if name == "state_probe":
            return reply(
                0,
                {"agent_id": self.agent_id, "config_fingerprint": "config-sha256"},
            )
        if name in {"previous_install", "current_install"}:
            if name == "previous_install":
                assert "signed_update" in self.phases_seen
            else:
                assert "previous_install" in self.phases_seen
            self.phases_seen.add(name)
            return reply(
                0, {"installed_version": "1.0.0" if name == "previous_install" else "2.0.0"}
            )
        if name == "heartbeat_probe":
            assert self.revoked
            self.phases_seen.add("revoked_protocol")
            return reply(0, {"heartbeat_status": 403, "claim_status": 403})
        if name == "cleanup_processes":
            self.cleanup_started = True
            return reply(0, {})
        raise AssertionError(f"unexpected command: {name}")

    def sleep(self, seconds):
        self.clock += seconds
        if self.status == "offline" and len(self.source_ids) == 2 and not self.catch_up_created:
            self._job("scan", "source-server", "catch_up")["status"] = "pending"
            self.catch_up_created = True

    def monotonic(self):
        return self.clock


def test_complete_smoke_is_stateful_fail_closed_and_covers_every_release_phase():
    smoke = smoke_module()
    scenario = Scenario(smoke)
    evidence = smoke.SmokeRunner(
        config(smoke),
        scenario,
        scenario,
        clock=scenario.monotonic,
        sleep=scenario.sleep,
    ).run()

    assert evidence["result"] == "passed"
    assert [phase["name"] for phase in evidence["phases"]] == [
        "enrollment",
        "remote_path_and_sources",
        "both_processing_modes",
        "offline_cache_and_catch_up",
        "reconciliation_and_reconnect",
        "signed_update_notification",
        "clean_upgrade",
        "revocation",
    ]
    assert all(phase["status"] == "passed" for phase in evidence["phases"])
    assert scenario.phases_seen >= {
        "enrollment",
        "enrollment_pending",
        "approved_offline",
        "agent_online",
        "remote_browse",
        "global_schedule",
        "source_schedule",
        "scan_on_agent",
        "scan_on_server",
        "search",
        "detail",
        "preview",
        "download_link",
        "download",
        "offline_search",
        "offline_detail",
        "offline_download_rejected",
        "rename_reconciled",
        "rename_removed_original",
        "deletion_reconciled",
        "reconnect",
        "signed_update",
        "previous_install",
        "current_install",
        "revocation",
        "revoked_protocol",
    }
    assert scenario.catch_up_created
    offline_phase = next(
        phase for phase in evidence["phases"] if phase["name"] == "offline_cache_and_catch_up"
    )
    assert offline_phase["observations"]["catch_up_reason"] == "catch_up"
    assert scenario.commands.index("update_check") < scenario.commands.index("heartbeat_probe")
    assert scenario.commands.index("current_install") < scenario.commands.index("heartbeat_probe")
    assert scenario.enrollment_code not in json.dumps(evidence)


def test_missing_input_fails_before_transport_side_effects():
    smoke = smoke_module()

    class NeverCalled:
        def request(self, *args, **kwargs):
            raise AssertionError("validation must run before HTTP")

    broken = config(smoke, admin_token="", commands={})
    with pytest.raises(ValueError):
        smoke.SmokeRunner(broken, NeverCalled(), None).run()


def test_primary_failure_survives_cleanup_failure_and_all_secrets_are_redacted():
    smoke = smoke_module()

    class BrokenScenario(Scenario):
        def request(self, method, path, body=None, headers=None):
            if (method, path) == ("POST", "/api/sources/test-path"):
                raise RuntimeError("primary admin-secret token=agent-secret")
            if method == "POST" and path.endswith("/revoke"):
                raise RuntimeError("cleanup code=one-time-secret")
            return super().request(method, path, body, headers)

        def run(self, argv, *, stdin=None, env=None):
            if len(argv) > 1 and argv[1] == "cleanup_processes":
                return self.smoke.Reply(1, {"password": "process-secret"})
            return super().run(argv, stdin=stdin, env=env)

    scenario = BrokenScenario(smoke)
    runner = smoke.SmokeRunner(config(smoke), scenario, scenario, sleep=scenario.sleep)
    with pytest.raises(smoke.SmokeRunError) as caught:
        runner.run()
    message = str(caught.value)
    serialized = json.dumps(smoke.redact(runner.evidence))
    assert "primary" in message and "cleanup" in message
    for secret in ("admin-secret", "agent-secret", "one-time-secret", "process-secret"):
        assert secret not in message
        assert secret not in serialized
    assert runner.evidence["result"] == "failed"
    assert len(runner.evidence["cleanup"]) >= 2


def test_cli_writes_redacted_failure_evidence_and_returns_nonzero(tmp_path, monkeypatch):
    smoke = smoke_module()
    scenario = Scenario(smoke)

    def fail_request(method, path, body=None, headers=None):
        raise RuntimeError("boom token=transport-secret")

    scenario.request = fail_request
    monkeypatch.setattr(smoke, "UrlTransport", lambda *_: scenario)
    monkeypatch.setattr(smoke, "SubprocessRunner", lambda: scenario)
    commands_file = tmp_path / "commands.json"
    commands_file.write_text(json.dumps(command_templates()), encoding="utf-8")
    evidence_file = tmp_path / "evidence.json"
    result = smoke.main(
        [
            "--url",
            "https://server",
            "--admin-token",
            "admin-secret",
            "--agent-name",
            "smoke-agent",
            "--fixture-agent-path",
            "/fixtures/agent",
            "--fixture-server-path",
            "/fixtures/server",
            "--commands-json",
            str(commands_file),
            "--previous-version",
            "1.0.0",
            "--current-version",
            "2.0.0",
            "--notification-regex",
            "available",
            "--original-marker",
            "copper-jupiter",
            "--renamed-marker",
            "violet-saturn",
            "--evidence",
            str(evidence_file),
        ]
    )
    contents = evidence_file.read_text(encoding="utf-8")
    assert result == 1
    assert json.loads(contents)["result"] == "failed"
    assert "admin-secret" not in contents
    assert "transport-secret" not in contents


def test_command_templates_reject_shell_strings_and_enrollment_secrets_in_argv():
    smoke = smoke_module()
    assert smoke.expand_command(
        '["agent", "enroll", "{server_url}"]', {"server_url": "https://server"}
    ) == ["agent", "enroll", "https://server"]
    with pytest.raises(ValueError):
        smoke.expand_command("agent enroll {server_url}", {"server_url": "https://server"})
    broken = command_templates()
    broken["enroll"] = '["agent", "enroll", "{enrollment_code}"]'
    with pytest.raises(ValueError, match="enrollment"):
        config(smoke, commands=broken).validate()


def test_redaction_covers_url_query_headers_and_evidence_bodies():
    smoke = smoke_module()
    secret = "super-secret"
    redacted = smoke.redact(
        {
            "Authorization": f"Bearer {secret}",
            "url": f"https://server/?token={secret}&code={secret}",
            "password": secret,
        }
    )
    assert secret not in str(redacted)
    assert redacted["password"] == "[REDACTED]"
