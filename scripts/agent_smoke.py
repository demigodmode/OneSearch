#!/usr/bin/env python
"""Fail-closed release smoke for a real OneSearch remote agent.

Every external operation is either an authenticated HTTP request or an explicit
JSON argv command hook.  Hooks are deliberately required: they make the two
machines (server and agent) visible to the release gate instead of turning a
log line into evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;&]+)"),
    re.compile(
        r"(?i)((?:admin[_-]?token|agent[_-]?token|token|password|code|enrollment[_-]?code)=)([^\s&]+)"
    ),
)
SECRET_VALUES = (
    "admin_token",
    "agent_token",
    "authorization",
    "password",
    "enrollment_code",
    "code",
)


def redact(value: Any) -> Any:
    """Remove credentials recursively before anything reaches evidence or stderr."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if str(key).lower().replace("-", "_") in SECRET_VALUES
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def expand_command(template: str, values: dict[str, str]) -> list[str]:
    """Expand only a JSON argv array; callers never invoke a shell."""
    try:
        argv = json.loads(template)
    except json.JSONDecodeError as error:
        raise ValueError("command templates must be JSON argv arrays") from error
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("command template must be a non-empty JSON argv array")
    try:
        return [item.format(**values) for item in argv]
    except KeyError as error:
        raise ValueError(f"unknown command placeholder: {error.args[0]}") from error


@dataclass
class Reply:
    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def request(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> Reply: ...


class CommandRunner(Protocol):
    def run(
        self, argv: list[str], *, stdin: str | None = None, env: dict[str, str] | None = None
    ) -> Reply: ...


class UrlTransport:
    def __init__(self, url: str, admin_token: str):
        self.url, self.admin_token = url.rstrip("/"), admin_token

    def request(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> Reply:
        payload = json.dumps(body).encode() if body is not None else None
        merged = {"Authorization": f"Bearer {self.admin_token}", **(headers or {})}
        if payload is not None:
            merged["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.url + path, data=payload, headers=merged, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 operator supplied URL
                raw = response.read()
                return Reply(
                    response.status,
                    json.loads(raw) if raw else None,
                    dict(response.headers.items()),
                )
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw.decode(errors="replace")
            return Reply(error.code, body, dict(error.headers.items()))


class SubprocessRunner:
    def run(
        self, argv: list[str], *, stdin: str | None = None, env: dict[str, str] | None = None
    ) -> Reply:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            shell=False,
            env={**os.environ, **(env or {})},
        )
        output = completed.stdout.strip()
        try:
            body: Any = json.loads(output) if output else None
        except json.JSONDecodeError:
            body = {"stdout": output, "stderr": completed.stderr.strip()}
        return Reply(completed.returncode, body)


REQUIRED_COMMANDS = {
    "enroll",
    "start",
    "stop",
    "rename_fixture",
    "delete_fixture",
    "restore_fixture",
    "update_check",
    "previous_install",
    "previous_start",
    "previous_stop",
    "current_install",
    "heartbeat_probe",
    "cleanup_processes",
}


@dataclass
class SmokeConfig:
    url: str
    admin_token: str
    agent_name: str
    fixture_agent_path: str
    fixture_server_path: str
    commands: dict[str, str]
    previous_version: str
    current_version: str
    notification_regex: str
    poll_attempts: int = 30
    poll_seconds: float = 1.0
    due_intervals: int = 2
    cleanup_evidence_on_failure: bool = False

    def validate(self) -> None:
        missing = [
            name
            for name, value in vars(self).items()
            if name
            in {
                "url",
                "admin_token",
                "agent_name",
                "fixture_agent_path",
                "fixture_server_path",
                "previous_version",
                "current_version",
                "notification_regex",
            }
            and not value
        ]
        missing.extend(sorted(REQUIRED_COMMANDS - set(self.commands)))
        invalid = [
            name
            for name, command in self.commands.items()
            if name in REQUIRED_COMMANDS and not _is_json_argv(command)
        ]
        if missing or invalid or self.due_intervals < 2:
            raise ValueError(
                "required release-smoke input missing or invalid: "
                + ", ".join(
                    missing
                    + [f"{name} command" for name in invalid]
                    + ([] if self.due_intervals >= 2 else ["due_intervals >= 2"])
                )
            )


def _is_json_argv(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        isinstance(parsed, list) and bool(parsed) and all(isinstance(part, str) for part in parsed)
    )


class SmokeRunner:
    def __init__(
        self,
        config: SmokeConfig,
        transport: Transport,
        commands: CommandRunner,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.config, self.transport, self.commands, self.clock, self.sleep = (
            config,
            transport,
            commands,
            clock,
            sleep,
        )
        self.evidence: dict[str, Any] = {
            "platform": sys.platform,
            "started_at": time.time(),
            "phases": [],
            "http": [],
            "commands": [],
            "cleanup": [],
        }
        self.agent_id: str | None = None
        self.source_ids: list[str] = []
        self.values = {
            "server_url": config.url,
            "agent_name": config.agent_name,
            "fixture_agent_path": config.fixture_agent_path,
            "fixture_server_path": config.fixture_server_path,
            "previous_version": config.previous_version,
            "current_version": config.current_version,
        }

    def http(
        self, method: str, path: str, body: Any = None, expected: set[int] | None = None
    ) -> Reply:
        expected = {200} if expected is None else expected
        reply = self.transport.request(method, path, body)
        self.evidence["http"].append(
            {"method": method, "path": redact(path), "body": redact(body), "status": reply.status}
        )
        if reply.status not in expected:
            raise RuntimeError(f"{method} {path} returned {reply.status}: {redact(reply.body)}")
        return reply

    def command(self, name: str, *, enrollment_code: str | None = None) -> Reply:
        argv = expand_command(self.config.commands[name], self.values)
        env = {"ONESEARCH_ENROLLMENT_CODE": enrollment_code} if enrollment_code else None
        reply = self.commands.run(argv, stdin=enrollment_code, env=env)
        self.evidence["commands"].append(
            {"name": name, "argv": redact(argv), "status": reply.status}
        )
        if reply.status != 0:
            raise RuntimeError(f"{name} failed: {redact(reply.body)}")
        return reply

    def phase(self, name: str, action) -> None:
        record = {"name": name, "started_at": time.time(), "status": "failed"}
        self.evidence["phases"].append(record)
        try:
            observations = action()
            record.update(status="passed", observations=redact(observations or {}))
        finally:
            record["ended_at"] = time.time()

    def poll_agent(self, expected: str) -> dict[str, Any]:
        last: Any = None
        for _ in range(self.config.poll_attempts):
            last = self.http("GET", f"/api/agents/{self.agent_id}").body
            if last.get("status") == expected:
                return last
            self.sleep(self.config.poll_seconds)
        raise RuntimeError(f"agent {self.agent_id} did not become {expected}: {redact(last)}")

    def poll_job(self, job_id: str) -> dict[str, Any]:
        # The server exposes recent job state on the admin agent resource, avoiding a false admin claim call.
        for _ in range(self.config.poll_attempts):
            agent = self.http("GET", f"/api/agents/{self.agent_id}").body
            for job in agent.get("recent_jobs", []):
                if job.get("id") == job_id and job.get("status") in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    if job["status"] != "completed":
                        raise RuntimeError(f"job {job_id} ended {job['status']}")
                    return job
            self.sleep(self.config.poll_seconds)
        raise RuntimeError(f"job {job_id} did not complete")

    def scan(self, source_id: str, mode: str) -> dict[str, Any]:
        reply = self.http("POST", f"/api/sources/{source_id}/reindex", expected={202}).body
        job = self.poll_job(reply["job_id"])
        if job.get("kind") != "scan":
            raise RuntimeError("scan endpoint did not create a scan job")
        return {"job_id": reply["job_id"], "mode": mode, "job": job}

    def run(self) -> dict[str, Any]:
        self.config.validate()  # must happen before first remote mutation
        started = self.clock()
        failed = False
        try:
            self.phase("enrollment", self._enrollment)
            self.phase("remote_path_and_sources", self._sources)
            self.phase("both_processing_modes", self._scan_and_search)
            self.phase("offline_cache_and_catch_up", self._offline)
            self.phase("reconciliation_and_reconnect", self._reconcile)
            self.phase("signed_update_notification", self._update)
            self.phase("clean_upgrade", self._upgrade)
            self.phase("revocation", self._revoke)
        except Exception:
            failed = True
            raise
        finally:
            cleanup_error = self._cleanup()
            self.evidence["duration_seconds"] = self.clock() - started
            self.evidence["result"] = "failed" if failed or cleanup_error else "passed"
            if cleanup_error:
                raise RuntimeError(cleanup_error)
        return self.evidence

    def _enrollment(self):
        code = self.http("POST", "/api/agents/enrollments", expected={201}).body.get("code")
        if not code:
            raise RuntimeError("enrollment response has no code")
        self.command("enroll", enrollment_code=code)
        agents = self.http("GET", "/api/agents").body
        matches = [
            agent
            for agent in agents
            if agent.get("name") == self.config.agent_name and agent.get("status") == "pending"
        ]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one pending agent with the requested name")
        self.agent_id = matches[0]["id"]
        self.http("POST", f"/api/agents/{self.agent_id}/approve")
        self.command("start")
        return {"agent": self.poll_agent("online")["id"]}

    def _sources(self):
        tested = self.http(
            "POST",
            "/api/sources/test-path",
            {
                "root_path": self.config.fixture_agent_path,
                "location_type": "agent",
                "agent_id": self.agent_id,
            },
        ).body
        if not tested.get("job_id"):
            raise RuntimeError("remote path test did not return a browse job")
        self.poll_job(tested["job_id"])
        payloads = [
            {
                "name": "smoke-on-agent",
                "root_path": self.config.fixture_agent_path,
                "location_type": "agent",
                "agent_id": self.agent_id,
                "processing_mode": "on_agent",
                "use_default_schedule": True,
            },
            {
                "name": "smoke-on-server",
                "root_path": self.config.fixture_server_path,
                "location_type": "agent",
                "agent_id": self.agent_id,
                "processing_mode": "on_server",
                "use_default_schedule": False,
                "schedule_type": "interval",
                "interval_value": 1,
                "interval_unit": "minutes",
            },
        ]
        responses = [
            self.http("POST", "/api/sources", payload, {201, 200}).body for payload in payloads
        ]
        self.source_ids = [source["id"] for source in responses]
        if (
            responses[0].get("use_default_schedule") is not True
            or responses[1].get("use_default_schedule") is not False
            or not all(source.get("effective_schedule") for source in responses)
        ):
            raise RuntimeError("source schedule inheritance/override was not returned")
        return {"sources": self.source_ids}

    def _scan_and_search(self):
        scans = [
            self.scan(source_id, mode)
            for source_id, mode in zip(self.source_ids, ("on_agent", "on_server"), strict=True)
        ]
        results = []
        for source_id in self.source_ids:
            found = self.http(
                "POST", "/api/search", {"q": "onesearch smoke fixture", "source_id": source_id}
            ).body
            if not found.get("results"):
                raise RuntimeError(f"search did not find fixture content for {source_id}")
            results.append(found["results"][0])
        if results[0]["id"] == results[1]["id"]:
            raise RuntimeError("the two fixture sources did not yield distinct content")
        document = self.http("GET", f"/api/documents/{results[0]['id']}").body
        if not document.get("content"):
            raise RuntimeError("stored document detail has no content")
        preview = self.http("GET", f"/api/documents/{results[0]['id']}/preview", expected={200})
        link = self.http("POST", f"/api/documents/{results[0]['id']}/download-link").body
        if preview.status != 200 or not link.get("url"):
            raise RuntimeError("online preview/download proof failed")
        self.values["document_id"] = results[0]["id"]
        self.values["download_path"] = link["url"]
        return {"scans": scans, "documents": [item["id"] for item in results]}

    def _offline(self):
        self.command("stop")
        self.poll_agent("offline")
        self.http("POST", "/api/search", {"q": "onesearch smoke fixture"})
        self.http("GET", f"/api/documents/{self.values['document_id']}")
        self.http("GET", self.values["download_path"], expected={409})
        self.command("stop")  # hook must demonstrate that it remains stopped, not merely report it
        for _ in range(self.config.due_intervals):
            self.sleep(60)
        self.command("start")
        agent = self.poll_agent("online")
        pending = [
            job
            for job in agent.get("recent_jobs", [])
            if job.get("kind") == "scan" and job.get("status") in {"pending", "claimed", "running"}
        ]
        if len(pending) != 1:
            raise RuntimeError("missed schedules did not coalesce to exactly one catch-up scan")
        self.poll_job(pending[0]["id"])
        return {"catch_up_job": pending[0]["id"]}

    def _reconcile(self):
        self.command("rename_fixture")
        self.scan(self.source_ids[0], "on_agent")
        renamed = self.http(
            "POST",
            "/api/search",
            {"q": "renamed onesearch smoke fixture", "source_id": self.source_ids[0]},
        ).body
        old = self.http(
            "POST", "/api/search", {"q": "onesearch smoke fixture", "source_id": self.source_ids[0]}
        ).body
        if not renamed.get("results") or old.get("results"):
            raise RuntimeError("rename reconciliation was not observed")
        self.command("delete_fixture")
        self.scan(self.source_ids[1], "on_server")
        deleted = self.http(
            "POST", "/api/search", {"q": "onesearch smoke fixture", "source_id": self.source_ids[1]}
        ).body
        if deleted.get("results"):
            raise RuntimeError("deleted fixture remained searchable")
        self.command("stop")
        self.poll_agent("offline")
        self.command("start")
        self.poll_agent("online")
        return {"reconciled": True}

    def _revoke(self):
        self.http("POST", f"/api/agents/{self.agent_id}/revoke")
        probe = self.command("heartbeat_probe")
        if not isinstance(probe.body, dict) or probe.body.get("status") not in {401, 403}:
            raise RuntimeError("revoked agent heartbeat/claim was not rejected")
        return {"probe_status": probe.body["status"]}

    def _update(self):
        update = self.command("update_check")
        text = json.dumps(update.body)
        if not re.search(self.config.notification_regex, text) or (
            isinstance(update.body, dict) and update.body.get("self_replaced")
        ):
            raise RuntimeError("signed update notification or Docker no-self-replace proof failed")
        return {"notification": True}

    def _upgrade(self):
        for name in (
            "previous_install",
            "previous_start",
            "previous_stop",
            "current_install",
            "start",
        ):
            self.command(name)
        agent = self.poll_agent("online")
        if agent.get("version") != self.config.current_version:
            raise RuntimeError("current agent version was not observed online after upgrade")
        if not self.http("POST", "/api/search", {"q": "renamed onesearch smoke fixture"}).body.get(
            "results"
        ):
            raise RuntimeError("upgrade lost indexed data")
        return {"version": agent["version"]}

    def _cleanup(self) -> str | None:
        errors = []
        for source_id in self.source_ids:
            try:
                self.http("DELETE", f"/api/sources/{source_id}", expected={204})
            except Exception as error:
                errors.append(f"source {source_id}: {redact(error)}")
        if self.agent_id:
            try:
                self.http("POST", f"/api/agents/{self.agent_id}/revoke", expected={200, 409})
            except Exception as error:
                errors.append(f"agent {self.agent_id}: {redact(error)}")
        for name in ("stop", "cleanup_processes", "restore_fixture"):
            try:
                self.command(name)
            except Exception as error:
                errors.append(f"{name}: {redact(error)}")
        self.evidence["cleanup"] = errors or ["completed"]
        return "; ".join(errors) if errors else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--admin-token")
    parser.add_argument("--admin-token-file", type=Path)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--fixture-agent-path", required=True)
    parser.add_argument("--fixture-server-path", required=True)
    parser.add_argument("--commands-json", type=Path, required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--notification-regex", required=True)
    parser.add_argument("--evidence", type=Path, default=Path("agent-smoke-evidence.json"))
    parser.add_argument("--poll-attempts", type=int, default=30)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--due-intervals", type=int, default=2)
    args = parser.parse_args()
    token = (
        args.admin_token
        or os.getenv("ONESEARCH_ADMIN_TOKEN")
        or (args.admin_token_file.read_text().strip() if args.admin_token_file else "")
    )
    try:
        config = SmokeConfig(
            args.url,
            token,
            args.agent_name,
            args.fixture_agent_path,
            args.fixture_server_path,
            json.loads(args.commands_json.read_text()),
            args.previous_version,
            args.current_version,
            args.notification_regex,
            args.poll_attempts,
            args.poll_seconds,
            args.due_intervals,
        )
        evidence = SmokeRunner(
            config, UrlTransport(config.url, config.admin_token), SubprocessRunner()
        ).run()
        args.evidence.write_text(json.dumps(redact(evidence), indent=2) + "\n", encoding="utf-8")
        print(json.dumps(redact(evidence), indent=2))
        return 0
    except Exception as error:
        print(redact(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
