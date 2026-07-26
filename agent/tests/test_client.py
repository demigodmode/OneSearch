import httpx
import pytest
from onesearch_agent.client import (
    AgentAmbiguousResultError,
    AgentClient,
    AgentError,
    AgentRevoked,
    JobConflict,
    RemoteAgentsDisabled,
    retry_delay,
)
from onesearch_shared import PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_claim_204_returns_none_and_headers_do_not_leak_token():
    seen = {}

    async def handler(request):
        seen.update(request.headers)
        return httpx.Response(204)

    async with AgentClient(
        "http://server.test", "top-secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert await client.heartbeat("1", "test") is not None
    assert seen["authorization"] == "Bearer top-secret"


@pytest.mark.asyncio
async def test_job_status_uses_authenticated_get_and_strict_response_model():
    seen = {}

    async def handler(request):
        seen["method"], seen["path"], seen["authorization"] = (
            request.method,
            request.url.path,
            request.headers.get("authorization"),
        )
        return httpx.Response(200, json={"job_id": "job", "status": "completed"})

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        response = await client.job_status("job")
    assert response.job_id == "job" and response.status == "completed"
    assert seen == {
        "method": "GET",
        "path": "/api/agent/v1/jobs/job/status",
        "authorization": "Bearer token",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim", "batch", "complete", "cancel"])
async def test_mutation_lost_response_is_one_request_and_ambiguous(operation):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost", request=request)

    class Body:
        def model_dump(self, mode):
            return {"job_id": "job"}

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentAmbiguousResultError):
            if operation == "claim":
                await client.claim()
            elif operation == "batch":
                await client.submit_batch("job", Body(), "lease")
            elif operation == "complete":
                await client.complete("job", Body(), "lease")
            else:
                await client.cancel_ack("job", "lease")
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_claim_server_ambiguity_is_not_replayed(status):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentAmbiguousResultError):
            await client.claim()
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim", "batch", "complete", "cancel"])
@pytest.mark.parametrize(
    "error_type", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError, httpx.ConnectError]
)
async def test_mutation_transport_errors_are_conservatively_one_request(operation, error_type):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if error_type is httpx.RemoteProtocolError:
            raise error_type("lost")
        raise error_type("lost", request=request)

    class Body:
        def model_dump(self, mode):
            return {"job_id": "job"}

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentAmbiguousResultError):
            if operation == "claim":
                await client.claim()
            elif operation == "batch":
                await client.submit_batch("job", Body(), "lease")
            elif operation == "complete":
                await client.complete("job", Body(), "lease")
            else:
                await client.cancel_ack("job", "lease")
    assert calls == 1


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
        assert await client.heartbeat("1", "test") is not None
    assert delays == [7]


@pytest.mark.asyncio
async def test_connect_error_retries_with_injected_delay():
    calls, delays = 0, []

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(204)

    async def sleep(delay):
        delays.append(delay)

    async with AgentClient(
        "http://server.test",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        random=lambda: 0,
    ) as client:
        assert await client.heartbeat("1", "test") is not None
    assert delays == [1, 2]


@pytest.mark.asyncio
async def test_status_errors_do_not_include_token():
    async def handler(request):
        return httpx.Response(500)

    async with AgentClient(
        "http://server.test",
        "top-secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: __import__("asyncio").sleep(0),
    ) as client:
        with pytest.raises(AgentError) as error:
            await client.heartbeat("1", "test")
    assert "top-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_client_timeout_and_injected_lifecycle():
    external = httpx.AsyncClient(base_url="http://server.test")
    async with AgentClient("http://ignored.test", client=external):
        assert not external.is_closed
    assert not external.is_closed
    await external.aclose()
    async with AgentClient(
        "http://server.test", transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ) as client:
        assert (
            client.client.timeout.read >= 30
            and client.client.timeout.connect == 5
            and client.client.timeout.write == 15
            and client.client.timeout.pool == 5
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "error"),
    [("remote_agents_disabled", RemoteAgentsDisabled), ("job state conflict", JobConflict)],
)
async def test_409_detail_mapping(detail, error):
    async def handler(request):
        return httpx.Response(409, json={"detail": detail})

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(error):
            await client.heartbeat("1", "test")


@pytest.mark.asyncio
async def test_all_job_endpoints_send_contract_headers_and_bodies():
    seen = []

    async def handler(request):
        seen.append(
            (
                request.url.path,
                request.headers["authorization"],
                request.headers["x-onesearch-protocol-version"],
                request.headers["user-agent"],
                request.headers["x-onesearch-lease-token"],
                request.content,
            )
        )
        return (
            httpx.Response(200, json={"batch_id": "b", "accepted_count": 0})
            if request.url.path.endswith("batches")
            else httpx.Response(200)
        )

    class Body:
        def model_dump(self, mode):
            return {"job_id": "job", "value": "ok"}

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        await client.job_heartbeat("job", Body(), "lease")
        await client.submit_batch("job", Body(), "lease")
        await client.complete("job", Body(), "lease")
        await client.cancel_ack("job", "lease")
    assert [item[0] for item in seen] == [
        "/api/agent/v1/jobs/job/heartbeat",
        "/api/agent/v1/jobs/job/batches",
        "/api/agent/v1/jobs/job/complete",
        "/api/agent/v1/jobs/job/cancel-ack",
    ]
    assert all(
        item[1] == "Bearer token" and item[2] == str(PROTOCOL_VERSION) and item[4] == "lease"
        for item in seen
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503])
async def test_server_errors_retry_then_stop(status):
    calls, delays = 0, []

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async def sleep(delay):
        delays.append(delay)

    async with AgentClient(
        "http://server.test",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        random=lambda: 0,
    ) as client:
        with pytest.raises(AgentError):
            await client.heartbeat("1", "test")
    assert calls == 4 and delays == [1, 2, 4]


@pytest.mark.asyncio
async def test_upload_chunk_500_is_ambiguous_once_with_raw_transport():
    seen, calls = {}, 0

    async def handler(request):
        nonlocal calls
        calls += 1
        seen["body"], seen["query"], seen["lease"] = (
            request.content,
            request.url.query.decode(),
            request.headers.get("X-OneSearch-Lease-Token"),
        )
        return httpx.Response(500)

    async with AgentClient(
        "http://server.test", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AgentAmbiguousResultError):
            await client.upload_file_chunk("job", "lease", sequence=2, data=b"raw", checksum="abc")
    assert calls == 1
    assert seen == {
        "body": b"raw",
        "query": "sequence=2&complete=false&checksum=abc",
        "lease": "lease",
    }
