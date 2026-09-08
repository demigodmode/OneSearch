import asyncio
from importlib.resources import files
from pathlib import Path

import pytest
from onesearch_agent.client import AgentDisabled, AgentPending, AgentRevoked
from onesearch_agent.runtime import run_runtime
from onesearch_agent.service import (
    ServiceError,
    _packaged_unit,
    _service_command,
    _systemd_arg,
    install,
    uninstall,
)


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


@pytest.mark.asyncio
async def test_runtime_reclaims_immediately_after_handling_a_job():
    # A handled job must not wait the idle interval before the next claim, so a
    # queue drains without the 30s dead window that stalled browse/validation.
    slept = []

    class Client:
        def __init__(self):
            self.claims = 0

        async def heartbeat(self, *args):
            pass

        async def claim(self):
            self.claims += 1
            return "lease"

    handled = []

    async def worker(lease, client):
        handled.append(lease)
        if len(handled) == 2:
            raise AgentRevoked()

    async def sleep(seconds):
        slept.append(seconds)

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), worker=worker, sleep=sleep)
    assert handled == ["lease", "lease"]
    assert slept == []  # drained back-to-back with no interval pause


@pytest.mark.asyncio
async def test_runtime_empty_claim_does_not_add_sleep_after_a_longpoll():
    slept = []
    ticks = iter([100.0, 130.0])  # the claim itself took 30s (>= floor)

    class Client:
        async def heartbeat(self, *args):
            pass

        async def claim(self):
            return None

    async def worker(*args):
        pass

    async def sleep(seconds):
        slept.append(seconds)
        raise AgentRevoked()

    with pytest.raises(AgentRevoked):
        await run_runtime(
            Client(),
            worker=worker,
            sleep=sleep,
            monotonic=lambda: next(ticks),
            claim_idle_floor=2.0,
        )
    assert slept == [0.0]  # long-poll was the wait; nothing extra added


@pytest.mark.asyncio
async def test_runtime_floors_a_fast_empty_claim_to_avoid_hot_loop():
    slept = []
    ticks = iter([100.0, 100.5])  # claim returned in 0.5s (server not long-polling)

    class Client:
        async def heartbeat(self, *args):
            pass

        async def claim(self):
            return None

    async def worker(*args):
        pass

    async def sleep(seconds):
        slept.append(seconds)
        raise AgentRevoked()

    with pytest.raises(AgentRevoked):
        await run_runtime(
            Client(),
            worker=worker,
            sleep=sleep,
            monotonic=lambda: next(ticks),
            claim_idle_floor=2.0,
        )
    assert slept == [1.5]  # floor - elapsed


@pytest.mark.asyncio
async def test_runtime_unapproved_agent_paces_with_interval():
    # AgentPending (approval pending) must keep the steady interval, never spin.
    slept = []

    class Client:
        def __init__(self):
            self.claims = 0

        async def heartbeat(self, *args):
            raise AgentPending()

        async def claim(self):
            self.claims += 1
            return None

    async def worker(*args):
        pass

    async def sleep(seconds):
        slept.append(seconds)
        raise AgentRevoked()

    client = Client()
    with pytest.raises(AgentRevoked):
        await run_runtime(client, worker=worker, sleep=sleep, interval=30)
    assert slept == [30]
    assert client.claims == 0  # heartbeat raised before any claim


@pytest.mark.asyncio
async def test_runtime_stops_after_handling_a_job_without_reclaiming():
    handled = {"n": 0}

    class Client:
        def __init__(self):
            self.claims = 0

        async def heartbeat(self, *args):
            pass

        async def claim(self):
            self.claims += 1
            return "lease"

    async def worker(lease, client):
        handled["n"] += 1

    client = Client()
    await run_runtime(client, worker=worker, stopped=lambda: handled["n"] >= 1)
    assert handled["n"] == 1
    assert client.claims == 1  # stop honored on the immediate re-claim path


@pytest.mark.asyncio
async def test_runtime_stop_interrupts_the_idle_floor_wait():
    started = asyncio.Event()
    stopped = asyncio.Event()
    ticks = iter([0.0, 0.1])  # fast empty claim -> a floor wait we then interrupt

    class Client:
        async def heartbeat(self, *args):
            pass

        async def claim(self):
            return None

    async def worker(*args):
        pass

    async def sleep(seconds):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        run_runtime(
            Client(),
            worker=worker,
            sleep=sleep,
            monotonic=lambda: next(ticks),
            wait_stopped=stopped.wait,
            claim_idle_floor=2.0,
        )
    )
    await started.wait()
    stopped.set()
    await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_runtime_disabled_agent_stays_alive_and_paces_without_claiming():
    # A disabled agent is reversible; it must not exit (which would hot-loop under a
    # container restart policy) and must not claim work while disabled.
    slept = []

    class Client:
        def __init__(self):
            self.claims = 0

        async def heartbeat(self, *args):
            raise AgentDisabled()

        async def claim(self):
            self.claims += 1
            return None

    async def worker(*args):
        pass

    async def sleep(seconds):
        slept.append(seconds)
        raise AgentRevoked()  # break out after the first paced retry

    client = Client()
    with pytest.raises(AgentRevoked):
        await run_runtime(client, worker=worker, sleep=sleep, interval=30)
    assert slept == [30]  # paced like pending, not a hot loop
    assert client.claims == 0  # never claimed while disabled


@pytest.mark.asyncio
async def test_runtime_resumes_after_reenable():
    # Once re-enabled, the same process picks up and claims again — no restart needed.
    events = []

    class Client:
        def __init__(self):
            self.beats = 0

        async def heartbeat(self, *args):
            self.beats += 1
            if self.beats == 1:
                events.append("disabled")
                raise AgentDisabled()
            events.append("online")

        async def claim(self):
            events.append("claim")
            raise AgentRevoked()  # stop once we've proven it resumed

    async def worker(*args):
        pass

    async def sleep(seconds):
        pass

    with pytest.raises(AgentRevoked):
        await run_runtime(Client(), worker=worker, sleep=sleep, interval=0)
    assert events == ["disabled", "online", "claim"]


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
    monkeypatch.setattr(
        "onesearch_agent.service.load_config",
        lambda path: type("C", (), {"state_dir": tmp_path / "state"})(),
    )
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
    monkeypatch.setattr(
        "onesearch_agent.service.load_config",
        lambda path: type("C", (), {"state_dir": tmp_path / "state"})(),
    )
    monkeypatch.setattr("onesearch_agent.service._run", lambda args: None)
    install(tmp_path / "config.toml", "/opt/agent", system="posix", home=tmp_path)
    unit = (tmp_path / ".config/systemd/user/onesearch-agent.service").read_text()
    assert "NoNewPrivileges=yes" in unit and "RestartSec=5s" in unit


def test_linux_service_grants_only_configured_state_directory(monkeypatch, tmp_path: Path):
    config = tmp_path / "state dir" / "agent%.toml"
    config.parent.mkdir()
    config.write_text('state_dir = "/srv/onesearch-agent-state with space%"')
    state_dir = Path("/srv/onesearch-agent-state with space%")
    monkeypatch.setattr("onesearch_agent.service.validate_service_backend", lambda path: None)
    monkeypatch.setattr(
        "onesearch_agent.service.load_config",
        lambda path: type("C", (), {"state_dir": state_dir})(),
    )
    monkeypatch.setattr("onesearch_agent.service._run", lambda args: None)
    install(config, "/opt/agent", system="posix", home=tmp_path)
    unit = (tmp_path / ".config/systemd/user/onesearch-agent.service").read_text()
    assert f"ReadWritePaths={_systemd_arg(str(state_dir))}" in unit
    assert ".local/state/onesearch-agent" not in unit


def test_packaged_unit_uses_resource_matching_authoritative_template(monkeypatch, tmp_path: Path):
    authoritative = Path("agent/packaging/onesearch-agent.service").read_text()
    assert files("onesearch_agent").joinpath("onesearch-agent.service").read_text() == authoritative
    monkeypatch.setattr(
        "onesearch_agent.service.load_config",
        lambda path: type("C", (), {"state_dir": tmp_path / "state"})(),
    )
    assert "ExecStart=" in _packaged_unit(tmp_path / "config.toml", "/opt/agent")


def test_service_command_distinguishes_frozen_agent_from_python_source(tmp_path: Path):
    config = tmp_path / "config.toml"
    assert _service_command(config, "/opt/onesearch-agent", frozen=True) == (
        '"/opt/onesearch-agent" --config ' + _systemd_arg(str(config)) + " run"
    )
    assert _service_command(config, "/usr/bin/python", frozen=False) == (
        '"/usr/bin/python" -m onesearch_agent.cli --config ' + _systemd_arg(str(config)) + " run"
    )
