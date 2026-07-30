import asyncio
from pathlib import Path

import pytest
from onesearch_agent.client import AgentDisabled, AgentPending, AgentRevoked
from onesearch_agent.runtime import run_runtime
from onesearch_agent.service import ServiceError, _systemd_arg, install, uninstall


class PendingClient:
    def __init__(self):
        self.claim_calls = 0

    async def heartbeat(self, *args):
        raise AgentPending()

    async def claim(self):
        self.claim_calls += 1


@pytest.mark.asyncio
async def test_runtime_does_not_claim_without_worker():
    client = PendingClient()

    async def stop(_):
        raise AgentRevoked()

    with pytest.raises(AgentRevoked):
        await run_runtime(client, sleep=stop)
    assert client.claim_calls == 0


@pytest.mark.asyncio
async def test_runtime_claims_only_with_worker():
    class Client:
        async def heartbeat(self, *args):
            pass

        async def claim(self):
            return "lease"

    seen = []

    async def worker(lease, client):
        seen.append(lease)
        raise AgentRevoked()

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), worker=worker)
    assert seen == ["lease"]


@pytest.mark.asyncio
async def test_runtime_treats_disabled_as_terminal():
    class Client:
        async def heartbeat(self, *args):
            raise AgentDisabled()

    with pytest.raises(AgentDisabled):
        await run_runtime(Client())


@pytest.mark.asyncio
async def test_runtime_caps_backoff_after_jitter():
    delays = []

    class Client:
        async def heartbeat(self, *args):
            raise __import__("onesearch_agent.client", fromlist=["AgentError"]).AgentError()

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 1:
            raise AgentRevoked()

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), sleep=sleep, random=lambda: 99)
    assert delays == [60]


@pytest.mark.asyncio
async def test_runtime_stops_before_another_heartbeat():
    calls = []

    class Client:
        async def heartbeat(self, *args):
            calls.append("heartbeat")

    await run_runtime(Client(), stopped=lambda: True)
    assert calls == []


@pytest.mark.asyncio
async def test_stop_interrupts_started_heartbeat_without_claim():
    started = asyncio.Event()
    stopped = asyncio.Event()
    claims = []

    class Client:
        async def heartbeat(self, *args):
            started.set()
            await asyncio.Event().wait()

        async def claim(self):
            claims.append(True)

    task = asyncio.create_task(run_runtime(Client(), wait_stopped=stopped.wait))
    await started.wait()
    stopped.set()
    await asyncio.wait_for(task, 1)
    assert claims == []


@pytest.mark.asyncio
async def test_stop_interrupts_started_normal_sleep_without_second_heartbeat():
    started = asyncio.Event()
    stopped = asyncio.Event()
    calls = []

    class Client:
        async def heartbeat(self, *args):
            calls.append(True)

    async def sleep(seconds):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(run_runtime(Client(), sleep=sleep, wait_stopped=stopped.wait))
    await started.wait()
    stopped.set()
    await asyncio.wait_for(task, 1)
    assert calls == [True]


@pytest.mark.parametrize(
    "value", ["bad\tpath", "bad\x01path", "bad\x7fpath", "bad\npath", "bad\x00path"]
)
def test_systemd_argument_rejects_control_characters(value):
    with pytest.raises(ServiceError):
        _systemd_arg(value)


def test_systemd_argument_escapes_safe_special_characters():
    assert _systemd_arg('C:\\safe path\\"name"%') == '"C:\\\\safe path\\\\\\"name\\"%%"'


@pytest.mark.asyncio
async def test_normal_progress_cancels_and_awaits_losing_stop_waiter():
    finalized = asyncio.Event()
    calls = []

    class Client:
        async def heartbeat(self, *args):
            calls.append(True)
            if len(calls) == 2:
                raise AgentRevoked()

    async def waiter():
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    async def sleep(seconds):
        return None

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), sleep=sleep, wait_stopped=waiter)
    assert calls == [True, True] and finalized.is_set()


@pytest.mark.asyncio
async def test_worker_can_acknowledge_cancellation_lease():
    class Client:
        async def heartbeat(self, *args):
            pass

        async def claim(self):
            return type("Lease", (), {"id": "job", "lease_token": "lease"})()

        async def cancel_ack(self, job, lease):
            assert (job, lease) == ("job", "lease")
            raise AgentRevoked()

    async def worker(lease, client):
        await client.cancel_ack(lease.id, lease.lease_token)

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), worker=worker)


def test_windows_service_uses_pywin32_argv(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("onesearch_agent.service.validate_service_backend", lambda path: None)
    monkeypatch.setattr("onesearch_agent.service.load_config", lambda path: object())
    monkeypatch.setattr(
        "onesearch_agent.service.credential_store",
        lambda config: type("S", (), {"load": lambda self: "secret"})(),
    )
    monkeypatch.setattr(
        "onesearch_agent.windows_service.install_service",
        lambda path, token: calls.append((path, token)),
    )
    monkeypatch.setattr(
        "onesearch_agent.windows_service.remove_service", lambda: calls.append(("remove",))
    )
    install(tmp_path / "config.toml", "C:/Program Files/agent.exe", system="nt")
    uninstall(system="nt")
    assert calls[0][1] == "secret" and calls[-1] == ("remove",)


def test_unsupported_service_fails(tmp_path: Path):
    with pytest.raises(ServiceError):
        install(tmp_path / "c", "agent", system="other")


def test_linux_service_writes_unit_and_reloads(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("onesearch_agent.service.validate_service_backend", lambda path: None)
    monkeypatch.setattr("onesearch_agent.service._run", lambda args: calls.append(args))
    install(tmp_path / "config.toml", "/opt/agent", system="posix", home=tmp_path)
    assert (tmp_path / ".config/systemd/user/onesearch-agent.service").exists()
    uninstall(system="posix", home=tmp_path)
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "onesearch-agent.service"],
        ["systemctl", "--user", "disable", "--now", "onesearch-agent.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_linux_service_installs_hardened_packaged_unit(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("onesearch_agent.service.validate_service_backend", lambda path: None)
    monkeypatch.setattr("onesearch_agent.service._run", lambda args: None)
    install(tmp_path / "config.toml", "/opt/agent", system="posix", home=tmp_path)
    unit = (tmp_path / ".config/systemd/user/onesearch-agent.service").read_text()
    assert "NoNewPrivileges=yes" in unit and "RestartSec=5s" in unit
