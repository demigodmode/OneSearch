"""Release-harness contract tests (all external effects are injected)."""

import importlib.util
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


def test_smoke_runner_requires_json_argv_and_redacts_enrollment_stdin():
    smoke = smoke_module()
    assert hasattr(smoke, "SmokeRunner")
    argv = smoke.expand_command(
        '["agent", "enroll", "{server_url}"]', {"server_url": "https://server"}
    )
    assert argv == ["agent", "enroll", "https://server"]
    assert "code-value" not in smoke.redact("Authorization: Bearer admin-token code=code-value")


def test_missing_input_fails_before_transport_side_effects():
    smoke = smoke_module()

    class NeverCalled:
        def request(self, *args, **kwargs):
            raise AssertionError("validation must run before HTTP")

    config = smoke.SmokeConfig(
        url="https://server",
        admin_token="",
        agent_name="smoke",
        fixture_agent_path="/fixtures/agent",
        fixture_server_path="/fixtures/server",
        commands={},
        previous_version="1.0",
        current_version="2.0",
        notification_regex="update",
    )
    with pytest.raises(ValueError):
        smoke.SmokeRunner(config, NeverCalled(), None).run()


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
