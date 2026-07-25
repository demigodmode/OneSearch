from pathlib import Path

import pytest

from onesearch_agent.client import AgentPending, AgentRevoked
from onesearch_agent.runtime import run_runtime
from onesearch_agent.service import ServiceError, install, uninstall


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


def test_windows_service_uses_sc_argv(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("onesearch_agent.service._run", lambda args: calls.append(args))
    install(tmp_path / "config.toml", "C:/Program Files/agent.exe", system="nt")
    uninstall(system="nt")
    assert calls[0][:2] == ["sc.exe", "create"] and calls[-1][:2] == ["sc.exe", "delete"]


def test_unsupported_service_fails(tmp_path: Path):
    with pytest.raises(ServiceError):
        install(tmp_path / "c", "agent", system="other")
