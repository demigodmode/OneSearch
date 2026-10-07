# API Overview

OneSearch provides a REST API for programmatic access to search, source management, and system status.

## Base URL

When running locally:

```
http://localhost:8000/api
```

For remote instances, replace `localhost` with your server's hostname or IP.

---

## API Documentation

OneSearch uses FastAPI, which provides interactive API documentation at two URLs:

### Swagger UI (Interactive)

```
http://localhost:8000/docs
```

You can try API calls directly in the browser, see request/response schemas, and explore all endpoints.

### ReDoc (Alternative)

```
http://localhost:8000/redoc
```

Clean, readable documentation better suited for browsing and reference.

In the Docker image, these routes are proxied through nginx too, so `http://localhost:8000/docs` works for normal local installs.

---

## Authentication

OneSearch uses JWT-based authentication. Most API endpoints require a valid token. The exceptions are the setup and login helpers, health checks, document downloads (authorized by the signed link, not the token), and the remote-agent protocol, which uses enrollment codes and agent tokens.

### Getting a Token

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

Response:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### Using the Token

Pass it in the `Authorization` header:

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer eyJhbGciOi..."
```

### Auth Endpoints

```http
GET  /api/auth/status   # Check whether setup is required (public)
POST /api/auth/setup    # Create initial admin account (first run only)
POST /api/auth/login    # Get a token
GET  /api/auth/me       # Check current user
POST /api/auth/logout   # Logout acknowledgement
```

Tokens expire after 24 hours by default (configurable via `SESSION_EXPIRE_HOURS`). Login is rate-limited to 5 attempts per minute by default (`AUTH_RATE_LIMIT`).

See [Authentication Guide](../administration/authentication.md) for more details.

---

## Endpoints

### Search and Documents

```http
POST /api/search
GET  /api/documents/{id}
GET  /api/documents/{id}/preview
POST /api/documents/{id}/download-link
GET  /api/documents/{id}/download?token=...
```

Search indexed documents with optional filters, fetch full indexed document records, stream authenticated previews for supported image/RAW documents, or create short-lived links to download original indexed files.

### Sources

```http
GET    /api/sources              # List all
POST   /api/sources              # Create
GET    /api/sources/{id}         # Get details
PUT    /api/sources/{id}         # Update
DELETE /api/sources/{id}         # Delete
POST   /api/sources/test-path     # Test a candidate root path before saving
GET    /api/sources/test-path/{job_id} # Result of a remote path test
GET    /api/sources/local-roots   # Allowed roots for the local folder picker
POST   /api/sources/browse-local  # List folders under an allowed root
POST   /api/sources/browse        # Queue a folder listing on a remote agent
GET    /api/sources/browse/{job_id} # Result of a remote folder listing
POST   /api/sources/{id}/reindex  # Trigger reindex
POST   /api/sources/{id}/clear-stale # Clean failed-file entries
```

### Settings

```http
GET /api/settings   # Read indexing, preview and scheduling settings
PUT /api/settings   # Update them
```

### Remote agents

```http
/api/agents/*       # Admin: enroll, approve, disable, revoke
/api/agent/v1/*     # Protocol used by the agents themselves
```

### Authentication

```http
GET  /api/auth/status       # Setup status (public)
POST /api/auth/setup        # Initial account creation
POST /api/auth/login        # Login, get JWT
GET  /api/auth/me           # Current user info
POST /api/auth/logout       # Logout acknowledgement
```

### Status & Health

```http
GET /api/health               # API health
GET /api/status               # Overall status
GET /api/status/{source_id}   # Source status
```

See the endpoint-specific pages for details:

- [Sources API](sources.md)
- [Search API](search.md)
- [Preview API](preview.md)
- [Settings API](settings.md)
- [Status & Health API](status.md)
- [Agents API](agents.md)

---

## Response Format

All responses are JSON.

### Success

Successful responses are JSON objects or arrays matching the endpoint. For example, `GET /api/sources` returns an array of source objects, while `POST /api/search` returns a search response with `results`, `total`, `limit`, `offset`, and `processing_time_ms`.

Some action endpoints also include a short message, such as reindex responses with `message` and `stats`. Reindexing a remote-agent source is queued instead: it returns `202` with `message`, `job_id`, `status` and `coalesced`, and no `stats`.

### Error

```json
{
  "detail": "Error message explaining what went wrong"
}
```

HTTP status codes follow REST conventions:

- `200 OK` - Success
- `201 Created` - Resource created
- `202 Accepted` - Queued for a remote agent (remote reindex)
- `204 No Content` - Source deleted
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing or invalid auth token
- `403 Forbidden` - Not allowed, such as setup after the first account exists or previews turned off
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource busy (e.g., source is already indexing) or agent unavailable
- `413` / `415` - Preview too large, or not supported for that file type
- `422 Unprocessable Entity` - Request body failed validation
- `429 Too Many Requests` - Rate limit exceeded (login and setup endpoints)
- `500 Internal Server Error` - Server error
- `502 Bad Gateway` - Search index cleanup failed while deleting a source or revoking an agent
- `503 Service Unavailable` - `/api/health` when Meilisearch is unavailable

---

## Quick Examples

### Search

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "q": "kubernetes",
    "limit": 10
  }'
```

### Add a Source

```bash
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Documents",
    "root_path": "/data/documents",
    "include_patterns": ["**/*.pdf", "**/*.md"],
    "scan_schedule": "@daily"
  }'
```

### Test a Source Path

```bash
curl -X POST http://localhost:8000/api/sources/test-path \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"root_path": "/data/documents"}'
```

This does not create or update a source. It reports whether OneSearch can see the path from inside the container, whether it is inside allowed roots, whether it exists, whether it is a directory, and whether it is readable.

### Trigger Reindex

```bash
curl -X POST http://localhost:8000/api/sources/documents/reindex \
  -H "Authorization: Bearer $TOKEN"
```

Use `full=true` to clear indexed metadata and rebuild every file from scratch, such as after a managed Meilisearch migration:

```bash
curl -X POST "http://localhost:8000/api/sources/documents/reindex?full=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Get Status

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## Request/Response Examples

### Search Request

```json
{
  "q": "docker deployment",
  "source_id": "docs",
  "type": "markdown",
  "limit": 20,
  "offset": 0
}
```

The `type` field accepts any indexed OneSearch document type. Common values include `text`, `markdown`, `code`, `config`, `pdf`, `docx`, `xlsx`, `pptx`, `rtf`, `epub`, `subtitle`, `comic`, `image`, `raw_image`, `media`, and `file`.

### Search Response

```json
{
  "results": [
    {
      "id": "docs--abc123def456",
      "path": "/data/docs/docker-guide.md",
      "basename": "docker-guide.md",
      "source_name": "Documents",
      "type": "markdown",
      "size_bytes": 12345,
      "modified_at": 1672531200,
      "snippet": "...highlighted <em>docker</em> deployment notes...",
      "score": 0.982
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0,
  "processing_time_ms": 15
}
```

### Source Object

```json
{
  "id": "documents",
  "name": "Documents",
  "root_path": "/data/documents",
  "include_patterns": ["**/*.pdf", "**/*.md", "**/*.txt"],
  "exclude_patterns": ["**/node_modules/**", "**/.git/**"],
  "scan_schedule": "@daily",
  "created_at": "2026-01-15T10:30:00",
  "updated_at": "2026-01-15T10:30:00",
  "last_scan_at": "2026-01-15T02:00:00",
  "next_scan_at": "2026-01-16T02:00:00"
}
```

---

## Rate Limiting

The login endpoint (`POST /api/auth/login`) is rate-limited to prevent brute force attacks. Default is 5 attempts per minute, configurable via `AUTH_RATE_LIMIT`. Other endpoints don't have rate limiting; use reasonable request rates for bulk operations.

---

## Pagination

Search results support pagination:

```json
{
  "q": "query",
  "limit": 20,    // Results per page (default: 20, max: 100)
  "offset": 0     // Skip N results
}
```

For the second page:

```json
{
  "q": "query",
  "limit": 20,
  "offset": 20
}
```

---

## Error Handling

### Common Errors

**400 Bad Request**: Invalid input (missing fields, invalid patterns, etc.)

**404 Not Found**: Source or resource doesn't exist

**500 Internal Server Error**: Server error (check logs)

### Example Error

```json
{
  "detail": "Root path does not exist"
}
```

Always check the `detail` field for error messages.

---

## Client Libraries

### Python

Use `requests`:

```python
import requests

TOKEN = "your-jwt-token"
response = requests.post(
    "http://localhost:8000/api/search",
    json={"q": "kubernetes", "limit": 10},
    headers={"Authorization": f"Bearer {TOKEN}"}
)
results = response.json()
```

### JavaScript/TypeScript

Use `fetch`:

```typescript
const TOKEN = "your-jwt-token";
const response = await fetch("http://localhost:8000/api/search", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${TOKEN}`
  },
  body: JSON.stringify({ q: "kubernetes", limit: 10 })
});
const results = await response.json();
```

### curl

All examples in this documentation use `curl` for portability.

---

## Next Steps

- [Sources API](sources.md) - Manage search sources
- [Search API](search.md) - Search documents
- [Preview API](preview.md) - Previews and downloads
- [Settings API](settings.md) - Indexing, preview and scheduling settings
- [Status & Health API](status.md) - Monitor system
- [Agents API](agents.md) - Remote agents

Or try the interactive docs at http://localhost:8000/docs
