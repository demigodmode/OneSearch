import asyncio

from onesearch_shared import REMOTE_MAX_BATCH_BYTES, REMOTE_MAX_MANIFEST_PAGE_BYTES

from app.request_body_limits import (
    REMOTE_AGENT_COMPLETION_BODY_LIMIT,
    RemoteAgentBodyLimitMiddleware,
)


def _scope(path, headers=()):
    return {"type": "http", "method": "POST", "path": path, "headers": list(headers)}


def _run(app, scope, messages):
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def test_declared_whitespace_inflated_batch_is_rejected_before_endpoint():
    called = []

    async def endpoint(*_args):
        called.append(True)

    body = b'{"job_id":"j","batch_id":"b","documents":[]}' + b" " * 20
    app = RemoteAgentBodyLimitMiddleware(endpoint, limits={"batches": len(body) - 1})
    sent = _run(
        app,
        _scope("/api/agent/v1/jobs/j/batches", [(b"content-length", str(len(body)).encode())]),
        [{"type": "http.request", "body": body, "more_body": False}],
    )
    assert sent[0]["status"] == 413 and called == []


def test_chunked_repeated_key_manifest_is_bounded_before_endpoint():
    called = []

    async def endpoint(*_args):
        called.append(True)

    body = b'{"job_id":"j","batch_id":"old","batch_id":"new","documents":[]}'
    app = RemoteAgentBodyLimitMiddleware(endpoint, limits={"manifest": len(body) - 1})
    sent = _run(
        app,
        _scope("/api/agent/v1/jobs/j/manifest"),
        [
            {"type": "http.request", "body": body[:10], "more_body": True},
            {"type": "http.request", "body": body[10:], "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413 and called == []


def test_manifest_page_and_outcome_bodies_share_the_bounded_page_limit():
    app = RemoteAgentBodyLimitMiddleware(lambda *_args: None)

    for suffix in ("manifest-pages", "page-outcomes"):
        assert (
            app._limit_for(_scope(f"/api/agent/v1/jobs/j/{suffix}"))
            == REMOTE_MAX_MANIFEST_PAGE_BYTES
        )


def test_chunked_manifest_page_is_rejected_before_endpoint_allocation():
    called = []

    async def endpoint(*_args):
        called.append(True)

    body = b'{"checksum":"' + b"a" * 64 + b'","page":{}}'
    app = RemoteAgentBodyLimitMiddleware(endpoint, limits={"manifest-pages": len(body) - 1})
    sent = _run(
        app,
        _scope("/api/agent/v1/jobs/j/manifest-pages"),
        [
            {"type": "http.request", "body": body[:8], "more_body": True},
            {"type": "http.request", "body": body[8:], "more_body": False},
        ],
    )

    assert sent[0]["status"] == 413 and called == []


def test_accepted_body_is_replayed_and_unrelated_route_is_not_capped():
    received = []

    async def endpoint(_scope, receive, _send):
        received.append(await receive())

    body = b'{"job_id":"j","batch_id":"b","documents":[]}'
    app = RemoteAgentBodyLimitMiddleware(endpoint, limits={"batches": len(body)})
    _run(
        app,
        _scope("/api/agent/v1/jobs/j/batches"),
        [{"type": "http.request", "body": body, "more_body": False}],
    )
    _run(
        app,
        _scope("/api/agent/v1/heartbeat"),
        [{"type": "http.request", "body": body * 2, "more_body": False}],
    )
    assert received == [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.request", "body": body * 2, "more_body": False},
    ]


def test_app_rejects_declared_oversize_batch_but_not_accepted_or_unrelated_requests(client):
    oversize = b" " * (REMOTE_MAX_BATCH_BYTES + 1)
    response = client.post("/api/agent/v1/jobs/j/batches", content=oversize)
    assert response.status_code == 413
    compact = b'{"job_id":"j","batch_id":"b","documents":[]}'
    near_limit = compact + b" " * (REMOTE_MAX_BATCH_BYTES - len(compact))
    accepted = client.post("/api/agent/v1/jobs/j/batches", content=near_limit)
    unrelated = client.post("/api/agent/v1/heartbeat", content=oversize)
    assert accepted.status_code != 413 and unrelated.status_code != 413


def test_app_rejects_oversize_manifest_pages_and_outcomes_before_validation(client):
    oversized = b" " * (REMOTE_MAX_MANIFEST_PAGE_BYTES + 1)

    for suffix in ("manifest-pages", "page-outcomes"):
        response = client.post(f"/api/agent/v1/jobs/j/{suffix}", content=oversized)
        assert response.status_code == 413
        assert response.json() == {"detail": "Request body too large"}


def test_completion_body_is_bounded_before_endpoint_or_json_parsing():
    called = []

    async def endpoint(*_args):
        called.append(True)

    body = b"{" + b" " * REMOTE_AGENT_COMPLETION_BODY_LIMIT
    app = RemoteAgentBodyLimitMiddleware(endpoint)
    sent = _run(
        app,
        _scope("/api/agent/v1/jobs/j/complete"),
        [{"type": "http.request", "body": body, "more_body": False}],
    )
    assert sent[0]["status"] == 413 and called == []
