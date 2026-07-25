import httpx
import pytest
from onesearch_agent.client import AgentClient, AgentError, AgentRevoked, retry_delay


@pytest.mark.asyncio
async def test_claim_204_returns_none_and_headers_do_not_leak_token():
    seen = {}

    async def handler(request):
        seen.update(request.headers)
        return httpx.Response(204)

    async with AgentClient(
        "http://server.test", "top-secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert await client.claim() is None
    assert seen["authorization"] == "Bearer top-secret"


@pytest.mark.asyncio
async def test_auth_status_maps_to_terminal_exception():
    async def handler(request):
        return httpx.Response(401)

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentRevoked):
            await client.heartbeat("1", "test")


def test_retry_backoff_is_capped():
    assert retry_delay(20, random=lambda: 0) == 60


@pytest.mark.asyncio
async def test_job_calls_send_lease_token_header():
    seen = []

    async def handler(request):
        seen.append((request.url.path, request.headers["X-OneSearch-Lease-Token"]))
        return httpx.Response(200, json={"status": "ok"})

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        await client.cancel_ack("job", "lease-secret")
    assert seen == [("/api/agent/v1/jobs/job/cancel-ack", "lease-secret")]


@pytest.mark.asyncio
async def test_enrollment_has_no_bearer_and_read_timeout_is_not_retried(tmp_path):
    calls = 0

    class Config:
        agent_name = "agent"
        allowed_roots = [{"root_id": "r", "path": str(tmp_path)}]

    async def handler(request):
        nonlocal calls
        calls += 1
        assert "authorization" not in request.headers
        raise httpx.ReadTimeout("uncertain")

    async with AgentClient(
        "http://server.test", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentError):
            await client.enroll("code", Config())
    assert calls == 1


@pytest.mark.asyncio
async def test_429_retry_after_controls_retry_delay():
    calls, delays = 0, []

    async def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429, headers={"Retry-After": "7"}) if calls == 1 else httpx.Response(204)
        )

    async def sleep(delay):
        delays.append(delay)

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler), sleep=sleep
    ) as client:
        assert await client.claim() is None
    assert delays == [7]
