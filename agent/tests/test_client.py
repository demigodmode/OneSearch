import httpx
import pytest
from onesearch_agent.client import AgentClient, AgentRevoked, retry_delay


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
