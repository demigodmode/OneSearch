# Agent API

OneSearch has two separate agent API surfaces:

- `/api/agents` is for administrators and uses the same user bearer token as other administrative APIs.
- `/api/agent/v1` is for the agent process. It uses a one-time enrollment code or an agent bearer token, depending on the endpoint.

An agent token cannot call the administrative API or sign in to the web interface. A user token cannot claim agent jobs.

Remote agents must be enabled in application settings before enrollment or protocol work can proceed.

## Administrative endpoints

Send a user token in `Authorization: Bearer <USER_TOKEN>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/agents/enrollments` | Create a single-use enrollment code that expires after 15 minutes. |
| `GET` | `/api/agents` | List agents with health and workload summaries. |
| `GET` | `/api/agents/{agent_id}` | Read allowed roots, attached sources, and the 10 most recent jobs. |
| `PATCH` | `/api/agents/{agent_id}` | Change the default processing mode inherited by sources without an override. |
| `POST` | `/api/agents/{agent_id}/approve` | Approve a pending agent or enable a disabled agent. |
| `POST` | `/api/agents/{agent_id}/disable` | Stop an agent from authenticating until it is enabled again. |
| `POST` | `/api/agents/{agent_id}/revoke` | Permanently invalidate the agent token. |

Create an enrollment code:

```http
POST /api/agents/enrollments HTTP/1.1
Authorization: Bearer <USER_TOKEN>
```

```json
{
  "code": "<ONE_TIME_CODE>",
  "expires_at": "2026-08-06T18:30:00Z"
}
```

The plaintext code is returned only in this response. The server stores its hash.

Change the agent default:

```http
PATCH /api/agents/agent-id HTTP/1.1
Authorization: Bearer <USER_TOKEN>
Content-Type: application/json

{
  "default_processing_mode": "on_server"
}
```

The allowed values are `on_agent` and `on_server`. This default is resolved when a scan job is created. A source with its own processing-mode override does not inherit it.

An agent response contains administrative data, not its bearer token:

```json
{
  "id": "agent-id",
  "name": "archive-node",
  "platform": "Linux-x86_64",
  "version": "1.3.0",
  "protocol_version": 2,
  "allowed_roots": [
    {
      "root_id": "documents",
      "path": "/srv/documents",
      "display_name": "Documents",
      "read_only": true
    }
  ],
  "default_processing_mode": "on_agent",
  "auto_update": false,
  "status": "offline",
  "approved_at": "2026-08-06T18:20:00Z",
  "last_seen_at": null,
  "disabled_at": null,
  "created_at": "2026-08-06T18:19:00Z",
  "updated_at": "2026-08-06T18:20:00Z",
  "summary": {
    "attached_sources": 1,
    "indexed_documents": 120,
    "pending_jobs": 0,
    "active_jobs": 0,
    "failed_jobs": 0,
    "earliest_next_scan_at": null
  }
}
```

## Agent protocol endpoints

Enrollment is the only protocol request that uses the one-time code and no bearer token:

```http
POST /api/agent/v1/enroll HTTP/1.1
Content-Type: application/json

{
  "protocol_version": 2,
  "enrollment_token": "<ONE_TIME_CODE>",
  "agent_name": "archive-node",
  "agent_version": "1.3.0",
  "platform": "Linux-x86_64",
  "allowed_roots": [
    {
      "root_id": "documents",
      "path": "/srv/documents",
      "display_name": "Documents",
      "read_only": true
    }
  ]
}
```

```json
{
  "protocol_version": 2,
  "agent_id": "agent-id",
  "agent_token": "<REDACTED>",
  "allowed_roots": [
    {
      "root_id": "documents",
      "path": "/srv/documents",
      "display_name": "Documents",
      "read_only": true
    }
  ]
}
```

The agent saves the returned token immediately. The new record remains `pending` until an administrator approves it.

All other protocol endpoints use `Authorization: Bearer <AGENT_TOKEN>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/agent/v1/revoke-self` | Revoke a newly issued token if local credential persistence fails. Pending agents may call it. |
| `POST` | `/api/agent/v1/heartbeat` | Report agent version, platform, protocol version, and current job. |
| `POST` | `/api/agent/v1/jobs/claim` | Long-poll for up to 25 seconds. Returns `204` when no job is available. |
| `GET` | `/api/agent/v1/jobs/{job_id}/status` | Read the server-side state of a job owned by this agent. |
| `POST` | `/api/agent/v1/jobs/{job_id}/heartbeat` | Extend a lease and report progress. |
| `POST` | `/api/agent/v1/jobs/{job_id}/batches` | Submit normalized documents for an on-agent job. |
| `POST` | `/api/agent/v1/jobs/{job_id}/manifest` | Submit scan and reconciliation metadata. |
| `POST` | `/api/agent/v1/jobs/{job_id}/complete` | Complete, fail, or cancel a leased job. |
| `POST` | `/api/agent/v1/jobs/{job_id}/cancel-ack` | Acknowledge a server-requested cancellation. |
| `PUT` | `/api/agent/v1/jobs/{job_id}/file-chunks` | Transfer bounded original-file chunks for on-server extraction or an authorized preview/download stream. |

Browse and path-test operations arrive as leased `browse` jobs. There is no separate agent browse endpoint.

## Leases and retries

A successful claim returns a job lease:

```json
{
  "id": "job-id",
  "kind": "scan",
  "source_id": "documents",
  "processing_mode": "on_agent",
  "payload": {},
  "lease_token": "<REDACTED>"
}
```

The agent must send the issued lease token in `X-OneSearch-Lease-Token` for job heartbeat, batch, manifest, completion, cancellation, and file-chunk requests. Leases expire if they are not renewed. A stale or incorrect lease receives `401`, and work can return to the pending queue.

Document batches use `batch_id` as an idempotency key within a job. Repeating the same batch ID with the same canonical payload returns an acknowledgement with `duplicate: true`. Reusing it with different content is a conflict.

```json
{
  "job_id": "job-id",
  "batch_id": "batch-0001",
  "documents": [
    {
      "source_id": "documents",
      "path": "reports/summary.txt",
      "title": "summary.txt",
      "content": "Indexed text",
      "mime_type": "text/plain",
      "size_bytes": 12,
      "modified_at": 1786040400000000000,
      "metadata": {
        "type": "text"
      }
    }
  ],
  "checkpoint": null
}
```

```json
{
  "batch_id": "batch-0001",
  "accepted_count": 1,
  "rejected_paths": {},
  "duplicate": false
}
```

Protocol timestamps are Unix UTC epoch seconds unless a field specifies nanoseconds. Remote scan and document `modified_at` values use epoch nanoseconds. Unknown fields and incompatible protocol versions are rejected. Do not log bearer tokens, enrollment codes, lease tokens, or original-file chunks.
