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

**Note**: In Docker deployment, these aren't proxied through nginx, so they're only accessible when running the backend directly during development.

---

## Authentication

OneSearch uses JWT-based authentication. All API endpoints (except setup and login) require a valid token.

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
  "token_type": "bearer"
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
POST /api/auth/setup    # Create initial admin account (first run only)
POST /api/auth/login    # Get a token
GET  /api/auth/me       # Check current user
```

Tokens expire after 24 hours by default (configurable via `SESSION_EXPIRE_HOURS`). Login is rate-limited to 5 attempts per minute by default (`AUTH_RATE_LIMIT`).

See [Authentication Guide](../administration/authentication.md) for more details.

---

## Endpoints

### Search

```http
POST /api/search
```

Search indexed documents with optional filters.

### Sources

```http
GET    /api/sources              # List all
POST   /api/sources              # Create
GET    /api/sources/{id}         # Get details
PUT    /api/sources/{id}         # Update
DELETE /api/sources/{id}         # Delete
POST   /api/sources/{id}/reindex # Trigger reindex
```

### Authentication

```http
POST /api/auth/setup          # Initial account creation
POST /api/auth/login          # Login, get JWT
GET  /api/auth/me             # Current user info
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
- [Status & Health API](status.md)

---

## Response Format

All responses are JSON.

### Success

```json
{
  "data": { ... },
  "message": "Success"
}
```

### Error

```json
{
  "detail": "Error message explaining what went wrong"
}
```

HTTP status codes follow REST conventions:

- `200 OK` - Success
- `201 Created` - Resource created
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing or invalid auth token
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource busy (e.g., source is already indexing)
- `429 Too Many Requests` - Rate limit exceeded (login endpoint)
- `500 Internal Server Error` - Server error

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
    "include_patterns": "**/*.pdf,**/*.md",
    "scan_schedule": "@daily"
  }'
```

### Trigger Reindex

```bash
curl -X POST http://localhost:8000/api/sources/documents/reindex \
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
  "type": "md",
  "limit": 20,
  "offset": 0
}
```

### Search Response

```json
{
  "hits": [
    {
      "id": "docs--abc123",
      "source_id": "docs",
      "source_name": "Documents",
      "path": "/data/docs/docker-guide.md",
      "basename": "docker-guide.md",
      "type": "md",
      "title": "Docker Deployment Guide",
      "content": "Full document content...",
      "snippet": "...highlighted <mark>docker</mark> <mark>deployment</mark>...",
      "size_bytes": 12345,
      "modified_at": 1672531200
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
  "include_patterns": "**/*.pdf,**/*.md,**/*.txt",
  "exclude_patterns": "**/node_modules/**,**/.git/**",
  "scan_schedule": "@daily",
  "total_files": 1234,
  "last_indexed_at": "2026-01-15T10:30:00Z",
  "last_scan_at": "2026-01-15T02:00:00Z",
  "next_scan_at": "2026-01-16T02:00:00Z"
}
```

---

## Rate Limiting

The login endpoint (`POST /api/auth/login`) is rate-limited to prevent brute force attacks. Default is 5 attempts per minute, configurable via `AUTH_RATE_LIMIT`. Other endpoints don't have rate limiting — use reasonable request rates for bulk operations.

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
  "detail": "Source path does not exist: /data/invalid"
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
- [Status & Health API](status.md) - Monitor system

Or try the interactive docs at http://localhost:8000/docs
