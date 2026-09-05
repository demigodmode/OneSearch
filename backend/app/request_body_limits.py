"""Raw ASGI request-body limits for remote agent submission endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from onesearch_shared import (
    REMOTE_MAX_BATCH_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
)

REMOTE_AGENT_BODY_LIMITS = {
    "batches": REMOTE_MAX_BATCH_BYTES,
    "manifest-pages": REMOTE_MAX_MANIFEST_PAGE_BYTES,
    "page-outcomes": REMOTE_MAX_MANIFEST_PAGE_BYTES,
    "complete": 1_048_576,
}
REMOTE_AGENT_COMPLETION_BODY_LIMIT = REMOTE_AGENT_BODY_LIMITS["complete"]


class RemoteAgentBodyLimitMiddleware:
    """Reject oversize remote payloads before FastAPI reads or parses their JSON."""

    def __init__(self, app, *, limits: dict[str, int] | None = None):
        self.app = app
        self.limits = limits or REMOTE_AGENT_BODY_LIMITS

    def _limit_for(self, scope) -> int | None:
        if scope["type"] != "http" or scope["method"] != "POST":
            return None
        path = scope["path"]
        prefix = "/api/agent/v1/jobs/"
        if not path.startswith(prefix):
            return None
        suffix = path.rsplit("/", 1)[-1]
        return self.limits.get(suffix)

    async def _too_large(self, send: Callable[..., Awaitable[None]]) -> None:
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        limit = self._limit_for(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._too_large(send)
                    return
            except ValueError:
                pass

        buffered, received = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, receive, send)
                return
            body = message.get("body", b"")
            received += len(body)
            if received > limit:
                await self._too_large(send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def replay_receive():
            return (
                buffered.pop(0)
                if buffered
                else {"type": "http.request", "body": b"", "more_body": False}
            )

        await self.app(scope, replay_receive, send)
