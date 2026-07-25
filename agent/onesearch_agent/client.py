"""Authenticated protocol transport; runtime does not claim without a worker."""

from __future__ import annotations

import asyncio
import random as _random

import httpx
from onesearch_shared import (
    PROTOCOL_VERSION,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
    AgentHeartbeat,
    AgentJobLease,
    BatchAck,
)

from . import __version__


class AgentError(RuntimeError):
    pass


class AgentRevoked(AgentError):  # noqa: N818
    pass


class AgentPending(AgentError):  # noqa: N818
    pass


class AgentIncompatible(AgentError):  # noqa: N818
    pass


class AgentDisabled(AgentError):  # noqa: N818
    pass


def retry_delay(attempt: int, *, random=_random.random) -> float:
    return min(60, (2**attempt) + random())


class AgentClient:
    def __init__(
        self, server_url, token=None, *, transport=None, sleep=asyncio.sleep, random=_random.random
    ):
        self.token, self.sleep, self.random = token, sleep, random
        self.client = httpx.AsyncClient(
            base_url=server_url,
            transport=transport,
            timeout=httpx.Timeout(35, connect=5, read=35, write=15, pool=5),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    def _headers(self, token=True):
        result = {
            "User-Agent": f"onesearch-agent/{__version__}",
            "X-OneSearch-Protocol-Version": str(PROTOCOL_VERSION),
        }
        if token and self.token:
            result["Authorization"] = f"Bearer {self.token}"
        return result

    async def _request(self, method, path, *, json=None, token=True, headers=None, retry=True):
        for attempt in range(4):
            try:
                request_headers = self._headers(token)
                request_headers.update(headers or {})
                response = await self.client.request(
                    method, path, json=json, headers=request_headers
                )
            except httpx.TransportError as error:
                if attempt == 3 or not retry:
                    raise AgentError("server connection failed") from error
                await self.sleep(retry_delay(attempt, random=self.random))
                continue
            if response.status_code == 401:
                raise AgentRevoked("agent credential was rejected")
            if response.status_code == 403:
                raise AgentPending("agent is pending or disabled")
            if response.status_code == 409:
                raise AgentIncompatible("agent protocol is incompatible")
            if retry and (response.status_code == 429 or response.status_code >= 500):
                if attempt == 3:
                    raise AgentError("server request failed")
                await self.sleep(retry_delay(attempt, random=self.random))
                continue
            response.raise_for_status()
            return response
        raise AgentError("server request failed")

    async def enroll(self, code, config):
        request = AgentEnrollmentRequest(
            enrollment_token=code,
            agent_name=config.agent_name,
            agent_version=__version__,
            platform=__import__("platform").platform(),
            allowed_roots=config.allowed_roots,
        )
        response = await self._request(
            "POST",
            "/api/agent/v1/enroll",
            json=request.model_dump(mode="json"),
            token=False,
            retry=False,
        )
        return AgentEnrollmentResponse.model_validate(response.json())

    async def heartbeat(self, version, platform):
        request = AgentHeartbeat(agent_version=version, platform=platform)
        return await self._request(
            "POST", "/api/agent/v1/heartbeat", json=request.model_dump(mode="json")
        )

    async def claim(self):
        response = await self._request("POST", "/api/agent/v1/jobs/claim")
        return (
            None if response.status_code == 204 else AgentJobLease.model_validate(response.json())
        )

    async def job_heartbeat(self, job_id, request, lease_token):
        return await self._request(
            "POST",
            f"/api/agent/v1/jobs/{job_id}/heartbeat",
            json=request.model_dump(mode="json"),
            headers={"X-OneSearch-Lease-Token": lease_token},
        )

    async def submit_batch(self, job_id, request, lease_token):
        return BatchAck.model_validate(
            (
                await self._request(
                    "POST",
                    f"/api/agent/v1/jobs/{job_id}/batches",
                    json=request.model_dump(mode="json"),
                    headers={"X-OneSearch-Lease-Token": lease_token},
                )
            ).json()
        )

    async def complete(self, job_id, request, lease_token):
        return await self._request(
            "POST",
            f"/api/agent/v1/jobs/{job_id}/complete",
            json=request.model_dump(mode="json"),
            headers={"X-OneSearch-Lease-Token": lease_token},
        )

    async def cancel_ack(self, job_id, lease_token):
        return await self._request(
            "POST",
            f"/api/agent/v1/jobs/{job_id}/cancel-ack",
            headers={"X-OneSearch-Lease-Token": lease_token},
        )
