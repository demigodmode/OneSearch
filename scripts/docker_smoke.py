#!/usr/bin/env python3
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only
"""Build and boot an isolated OneSearch image, then index and search a fixture."""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STARTUP_SECONDS = 300
INDEX_SECONDS = 120
BUILD_SECONDS = 1200
SOURCE_ROOT = "/smoke-fixture"


class SmokeError(Exception):
    """A failed smoke assertion or Docker command."""


def validate_sha(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("SHA must be a full, lowercase 40-character commit ID")
    return value


def validate_run_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,40}", value):
        raise ValueError("run ID must be 1-41 safe Docker-name characters")
    return value


def health_ready(status, body):
    if not isinstance(body, dict) or not isinstance(body.get("meilisearch"), dict):
        return False
    return (
        status == 200
        and body.get("status") == "healthy"
        and body["meilisearch"].get("status") == "available"
        and body.get("setup_required") is True
    )


def search_found(body, source_id, fixture_name):
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        return False
    return any(
        isinstance(hit, dict)
        and hit.get("source_id") == source_id
        and isinstance(hit.get("path"), str)
        and Path(hit["path"]).name == fixture_name
        for hit in body.get("results", [])
    )


def wait_for_health(
    request, alive, deadline_seconds=STARTUP_SECONDS, sleep=time.sleep, clock=time.monotonic
):
    deadline = clock() + deadline_seconds
    while True:
        if not alive():
            raise SmokeError("container exited or became unhealthy during startup")
        status, body = request("GET", "/api/health")
        if health_ready(status, body):
            return
        if clock() >= deadline:
            raise SmokeError("startup health deadline exceeded")
        sleep(min(2, max(0, deadline - clock())))


def _expect(request, method, path, payload, expected, auth=None, timeout=10):
    status, body = request(method, path, payload, auth, timeout)
    if status != expected or not isinstance(body, dict):
        raise SmokeError(f"{path} returned HTTP {status}, expected {expected}")
    return body


def exercise_api(
    request,
    username,
    password,
    fixture_name,
    search_token,
    alive,
    deadline_seconds=INDEX_SECONDS,
    sleep=time.sleep,
    clock=time.monotonic,
):
    setup = _expect(
        request, "POST", "/api/auth/setup", {"username": username, "password": password}, 200
    )
    if not isinstance(setup.get("access_token"), str) or not setup["access_token"]:
        raise SmokeError("setup omitted access token")
    login = _expect(
        request, "POST", "/api/auth/login", {"username": username, "password": password}, 200
    )
    auth = login.get("access_token")
    if not isinstance(auth, str) or not auth:
        raise SmokeError("login omitted access token")
    source = _expect(
        request,
        "POST",
        "/api/sources",
        {"name": "Docker smoke fixture", "root_path": SOURCE_ROOT},
        201,
        auth,
    )
    source_id = source.get("id")
    if not isinstance(source_id, str) or not source_id or source.get("root_path") != SOURCE_ROOT:
        raise SmokeError("created source did not match smoke fixture")
    deadline = clock() + deadline_seconds
    if not alive():
        raise SmokeError("container exited before indexing")
    reindex = _expect(
        request,
        "POST",
        f"/api/sources/{source_id}/reindex",
        None,
        200,
        auth,
        timeout=max(1, deadline - clock()),
    )
    stats = reindex.get("stats", {})
    if not isinstance(stats, dict) or stats.get("failed", 0) != 0 or stats.get("successful", 0) < 1:
        raise SmokeError("fixture indexing reported no successful file or a failure")
    while True:
        if not alive():
            raise SmokeError("container exited during search")
        status, body = request(
            "POST", "/api/search", {"q": search_token, "source_id": source_id}, auth, 10
        )
        if status != 200:
            raise SmokeError(f"search returned HTTP {status}")
        if search_found(body, source_id, fixture_name):
            negative = _expect(
                request,
                "POST",
                "/api/search",
                {"q": "nevermatch" + search_token, "source_id": source_id},
                200,
                auth,
            )
            if not isinstance(negative.get("results"), list) or negative["results"]:
                raise SmokeError("negative search returned documents for an absent token")
            return {"source_id": source_id}
        if clock() >= deadline:
            raise SmokeError("search deadline exceeded without fixture hit")
        sleep(min(2, max(0, deadline - clock())))


def docker_command(args, timeout=15, redactions=(), environment=None):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False, env=environment
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeError(
            f"Docker command failed: {' '.join(args[:3])}: {type(exc).__name__}"
        ) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        for secret in redactions:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        detail = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", detail, flags=re.IGNORECASE)
        detail = detail[:1800]
        raise SmokeError(
            f"Docker command failed: {' '.join(args[:3])} (exit {result.returncode}): {detail}"
        )
    if len(args) > 1 and args[1] == "logs":
        return (result.stdout + result.stderr).strip()
    return result.stdout.strip()


class OwnedDocker:
    def __init__(self, command=docker_command):
        self.command = command
        self.created = []

    def record(self, kind, name):
        self.created.append((kind, name))

    def create(self, kind, name, args, **kwargs):
        # Register first: a daemon can create a resource before reporting failure.
        self.record(kind, name)
        return self.command(args, **kwargs)

    def cleanup(self):
        errors = []
        operations = {
            "container": ["docker", "rm", "-f"],
            "volume": ["docker", "volume", "rm"],
            "network": ["docker", "network", "rm"],
            "image": ["docker", "image", "rm", "-f"],
        }
        for kind, name in reversed(self.created):
            try:
                self.command([*operations[kind], name], timeout=30)
            except SmokeError as exc:
                errors.append(f"{kind} {name}: {exc}")
        self.created.clear()
        return errors


def request_client(base_url):
    def request(method, path, payload=None, auth=None, timeout=10):
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, {}
        except (URLError, TimeoutError, OSError):
            return 0, {}

    return request


def container_environment(meili_key, session_secret):
    return {
        "ONESEARCH_MANAGED_MEILI": "true",
        "MEILI_MASTER_KEY": meili_key,
        "SESSION_SECRET": session_secret,
        "DATABASE_URL": "sqlite:////app/data/onesearch.db",
        "ALLOWED_SOURCE_PATHS": SOURCE_ROOT,
        "SCHEDULER_ENABLED": "false",
    }


def container_environment_flags(values):
    return [part for key in values for part in ("--env", key)]


def _build_image(context, image, build_log):
    with build_log.open("w", encoding="utf-8") as output:
        try:
            result = subprocess.run(
                ["docker", "build", "--platform", "linux/amd64", "-t", image, str(context)],
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=BUILD_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SmokeError(f"Docker build failed: {type(exc).__name__}") from exc
    if result.returncode:
        tail = build_log.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise SmokeError(f"Docker build failed (exit {result.returncode}):\n{tail}")


def _write_summary(lines):
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def _diagnostics(container, redactions):
    try:
        state = docker_command(
            ["docker", "inspect", "--format", "{{json .State}}", container], timeout=10
        )
        print("Container state: " + state[:3000], file=sys.stderr)
    except SmokeError:
        print("Container state unavailable", file=sys.stderr)
    try:
        logs = docker_command(["docker", "logs", "--tail", "120", container], timeout=10)
        for secret in redactions:
            if secret:
                logs = logs.replace(secret, "[redacted]")
        logs = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", logs, flags=re.IGNORECASE)
        print("Container logs (bounded):\n" + logs[-12000:], file=sys.stderr)
    except SmokeError:
        print("Container logs unavailable", file=sys.stderr)


def summary_lines(sha, image_id, step, passed, elapsed, timings, cleanup_errors):
    timing_text = ", ".join(f"{name} {seconds:.1f}s" for name, seconds in timings.items())
    return [
        "### OneSearch Docker startup smoke",
        f"- Source SHA: `{sha}`",
        f"- Image ID: `{image_id or 'unavailable'}`",
        f"- Checks: {'health, setup, login, source, index, search' if passed else 'failed at ' + step}",
        f"- Timings: {timing_text or 'unavailable'}",
        f"- Elapsed: {elapsed:.1f}s",
        f"- Cleanup: {'complete' if not cleanup_errors else 'incomplete: ' + '; '.join(cleanup_errors)}",
    ]


def run_smoke(sha, run_id, context):
    validate_sha(sha)
    validate_run_id(run_id)
    context = Path(context).resolve()
    actual_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=context,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if actual_sha != sha:
        raise SmokeError("worktree HEAD differs from requested smoke SHA")

    name = f"onesearch-smoke-{run_id.lower()}-{secrets.token_hex(4)}"
    image = f"onesearch-smoke:{run_id.lower()}-{name[-8:]}"
    container = name + "-app"
    network = name + "-net"
    data_volume = name + "-data"
    index_volume = name + "-index"
    owner = OwnedDocker()
    started = time.monotonic()
    step = "prepare"
    image_id = ""
    passed = False
    error = ""
    cleanup_errors = []
    timings = {}
    with tempfile.TemporaryDirectory(prefix="onesearch-smoke-") as temporary:
        root = Path(temporary)
        fixture_dir = root / "fixture"
        fixture_dir.mkdir()
        fixture_name = "fixture.txt"
        search_token = "smokeorbit" + secrets.token_hex(8)
        (fixture_dir / fixture_name).write_text(
            f"OneSearch Docker smoke document. Search token: {search_token}\n", encoding="utf-8"
        )
        username = "smoke-admin"
        password = secrets.token_urlsafe(24)
        meili_key = secrets.token_urlsafe(32)
        session_secret = secrets.token_urlsafe(32)
        container_env = container_environment(meili_key, session_secret)
        try:
            step = "build"
            _build_image(context, image, root / "build.log")
            timings["build"] = time.monotonic() - started
            stage_started = time.monotonic()
            owner.record("image", image)
            image_id = docker_command(["docker", "image", "inspect", "--format", "{{.Id}}", image])
            step = "create isolated resources"
            owner.create("network", network, ["docker", "network", "create", network])
            for volume in (data_volume, index_volume):
                owner.create("volume", volume, ["docker", "volume", "create", volume])
            step = "start"
            owner.create(
                "container",
                container,
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    container,
                    "--network",
                    network,
                    "--cpus",
                    "2",
                    "--memory",
                    "3g",
                    "--pids-limit",
                    "512",
                    "--publish",
                    "127.0.0.1::8000",
                    *container_environment_flags(container_env),
                    "--mount",
                    f"type=volume,src={data_volume},dst=/app/data",
                    "--mount",
                    f"type=volume,src={index_volume},dst=/app/meili_data",
                    "--mount",
                    f"type=bind,src={fixture_dir},dst={SOURCE_ROOT},readonly",
                    image,
                ],
                timeout=60,
                redactions=(password, meili_key, session_secret),
                environment={**os.environ, **container_env},
            )
            port = docker_command(["docker", "port", container, "8000/tcp"])
            match = re.search(r"127\.0\.0\.1:(\d+)", port)
            if not match:
                raise SmokeError("Docker did not publish a loopback port")
            request = request_client(f"http://127.0.0.1:{match.group(1)}")

            def alive():
                state = docker_command(
                    ["docker", "inspect", "--format", "{{json .State}}", container]
                )
                info = json.loads(state)
                return (
                    info.get("Running") is True
                    and info.get("Health", {}).get("Status") != "unhealthy"
                )

            step = "startup health"
            wait_for_health(request, alive)
            timings["startup"] = time.monotonic() - stage_started
            stage_started = time.monotonic()
            step = "setup, login, index and search"
            exercise_api(request, username, password, fixture_name, search_token, alive)
            timings["api"] = time.monotonic() - stage_started
            passed = True
        except (SmokeError, ValueError, subprocess.CalledProcessError) as exc:
            error = str(exc)
            print(f"Smoke failed at {step}: {error}", file=sys.stderr)
            if step not in ("prepare", "build", "create isolated resources"):
                _diagnostics(container, (password, meili_key, session_secret))
        finally:
            cleanup_errors = owner.cleanup()

    elapsed = round(time.monotonic() - started, 1)
    lines = summary_lines(sha, image_id, step, passed, elapsed, timings, cleanup_errors)
    _write_summary(lines)
    if error or cleanup_errors:
        if cleanup_errors:
            print("Smoke cleanup incomplete: " + "; ".join(cleanup_errors), file=sys.stderr)
        return 1
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"image_id={image_id}\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="Full immutable source commit SHA")
    parser.add_argument("--run-id", required=True, help="Unique CI run and attempt identifier")
    parser.add_argument("--context", default=".", help="Repository build context")
    args = parser.parse_args()
    try:
        return run_smoke(args.sha, args.run_id, args.context)
    except (ValueError, SmokeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Smoke failed before container start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
