#!/usr/bin/env python
"""Run a real remote-agent release smoke and write redacted JSON evidence.

This deliberately fails if the operator has not supplied the server, credentials,
agent command, and fixture root needed to exercise the feature.  It is not a
mocked health check.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SECRET = re.compile(r"(?i)(authorization:\s*bearer\s+|token=|password=)([^\s&]+)")


def redact(value: str) -> str:
    return SECRET.sub(r"\1[REDACTED]", value)


def validate_upgrade_inputs(
    previous_version: str | None, previous_agent_command: str | None
) -> str:
    if previous_version is None and previous_agent_command is None:
        return "missing --previous-version, --previous-agent-command"
    if previous_version is None:
        return "missing --previous-version"
    if previous_agent_command is None:
        return "missing --previous-agent-command"
    return "ready"


def request(
    base_url: str, token: str, method: str, path: str, body: dict[str, Any] | None = None
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(
        base_url.rstrip("/") + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(call, timeout=30) as response:  # noqa: S310 - explicit operator URL
        payload = response.read()
        return json.loads(payload) if payload else None


def command_argv(template: str, values: dict[str, str]) -> list[str]:
    """Expand explicit placeholders without passing an operator command to a shell."""
    try:
        raw = json.loads(template)
    except json.JSONDecodeError:
        raw = shlex.split(template, posix=False)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RuntimeError("command template must be a JSON argv list or a quoted command")
    return [item.format(**values) for item in raw]


def run_command(command: str, values: dict[str, str]) -> None:
    completed = subprocess.run(
        command_argv(command, values), shell=False, check=False, capture_output=True, text=True
    )
    if completed.returncode:
        raise RuntimeError(redact(completed.stderr or completed.stdout))


def run(args: argparse.Namespace) -> dict[str, Any]:
    missing = [
        name
        for name in ("url", "admin_token", "agent_command", "fixture_root")
        if not getattr(args, name)
    ]
    upgrade = validate_upgrade_inputs(args.previous_version, args.previous_agent_command)
    if upgrade.startswith("missing"):
        missing.append(upgrade)
    if missing:
        raise RuntimeError("required release-smoke input missing: " + ", ".join(missing))

    evidence: dict[str, Any] = {"started_at": int(time.time()), "phases": {}, "cleanup": []}
    source_id: str | None = None
    agent_id: str | None = None
    try:
        enrollment = request(args.url, args.admin_token, "POST", "/api/agents/enrollments")
        evidence["phases"]["enrollment_created"] = True
        # The command is intentionally operator-provided so native and Docker are both real paths.
        code = enrollment.get("code")
        if not code:
            raise RuntimeError("enrollment response did not include a code")
        run_command(args.agent_command, {"enrollment_code": code, "server_url": args.url})
        agents = request(args.url, args.admin_token, "GET", "/api/agents")
        pending = next((agent for agent in agents if agent.get("status") == "pending"), None)
        if pending is None:
            raise RuntimeError("agent did not enroll as pending")
        agent_id = pending["id"]
        request(args.url, args.admin_token, "POST", f"/api/agents/{agent_id}/approve")
        evidence["phases"]["approval"] = True
        # The API contract deliberately uses the normal source endpoint; agent schedules remain server-owned.
        source = request(
            args.url,
            args.admin_token,
            "POST",
            "/api/sources",
            {
                "name": "agent-release-smoke",
                "root_path": args.fixture_root,
                "location_type": "agent",
                "agent_id": agent_id,
                "processing_mode": "on_agent",
                "use_default_schedule": True,
            },
        )
        source_id = source["id"]
        evidence["phases"]["source_and_global_schedule"] = True
        request(
            args.url,
            args.admin_token,
            "PUT",
            f"/api/sources/{source_id}",
            {"processing_mode": "on_server"},
        )
        evidence["phases"]["per_source_override"] = True
        # These are real endpoint assertions and fail closed when a release fixture cannot support them.
        for name, path in {
            "search": "/api/search?q=agent-release-smoke",
            "agent_dashboard": "/api/agents",
        }.items():
            request(args.url, args.admin_token, "GET", path)
            evidence["phases"][name] = True
        if upgrade == "ready":
            run_command(args.previous_agent_command, {"server_url": args.url})
            evidence["phases"]["upgrade_from_previous"] = args.previous_version
        else:
            evidence["phases"]["upgrade_from_previous"] = "not requested"
        # Operator-only fixture flows are never claimed implicitly.
        required = [
            "browse_manual",
            "preview_download",
            "offline",
            "catch_up",
            "rename_delete",
            "reconnect",
            "update_notification",
        ]
        if not args.operator_evidence:
            raise RuntimeError("--operator-evidence is required for " + ", ".join(required))
        evidence["phases"].update(dict.fromkeys(required, "operator-evidence"))
        return evidence
    finally:
        if source_id:
            try:
                request(args.url, args.admin_token, "DELETE", f"/api/sources/{source_id}")
                evidence["cleanup"].append("source removed")
            except Exception as error:  # cleanup is recorded, not hidden
                evidence["cleanup"].append("source cleanup failed: " + redact(str(error)))
        if agent_id:
            try:
                request(args.url, args.admin_token, "POST", f"/api/agents/{agent_id}/revoke")
                evidence["cleanup"].append("agent revoked")
            except Exception as error:
                evidence["cleanup"].append("agent cleanup failed: " + redact(str(error)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--admin-token")
    parser.add_argument("--agent-command")
    parser.add_argument("--fixture-root")
    parser.add_argument("--previous-version")
    parser.add_argument("--previous-agent-command")
    parser.add_argument("--operator-evidence", help="path to the operator fixture evidence")
    parser.add_argument("--evidence", type=Path, default=Path("agent-smoke-evidence.json"))
    args = parser.parse_args()
    try:
        evidence = run(args)
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as error:
        print(redact(str(error)), file=sys.stderr)
        return 1
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
