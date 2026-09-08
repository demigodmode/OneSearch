# Search API

Use this when you want to query indexed documents from a script, integration, or anything outside the web UI.

All search endpoints require a bearer token. Get one from `POST /api/auth/login` or use the CLI if you prefer not to handle tokens directly.

## Search documents

```http
POST /api/search
```

Request body:

```json
{
  "q": "kubernetes",
  "source_id": "documents",
  "type": "markdown",
  "limit": 20,
  "offset": 0,
  "sort": "relevance",
  "snippet_length": 300
}
```

Only `q` is required.

- `source_id` filters to one source.
- `type` filters by OneSearch document type, such as `text`, `markdown`, `code`, `config`, `pdf`, `docx`, `xlsx`, `pptx`, `rtf`, `epub`, `subtitle`, `comic`, `image`, `raw_image`, `media`, or `file`.
- `limit` is 1-100. Default is 20.
- `offset` is for pagination.
- `sort` can be `relevance`, `modified_at:desc`, `modified_at:asc`, `size_bytes:desc`, or `basename:asc`.
- `snippet_length` is 50-1000 characters. Default is 300.

Example:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "q": "kubernetes",
    "type": "markdown",
    "limit": 10
  }'
```

Response:

```json
{
  "results": [
    {
      "id": "documents--abc123def456",
      "path": "/data/docs/kubernetes-notes.md",
      "basename": "kubernetes-notes.md",
      "source_name": "Documents",
      "type": "markdown",
      "size_bytes": 12345,
      "modified_at": 1715791200,
      "snippet": "...notes about <em>kubernetes</em> deployments...",
      "score": 0.987
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0,
  "processing_time_ms": 4
}
```

Each result also includes `source_id` and `agent_status`. Local sources have `agent_status: null`. For remote sources, the status is computed from the agent's current access state, heartbeat freshness, and the global Remote agents setting: `online`, `offline`, `disabled`, or `revoked`. A connected agent with degraded indexing health counts as `online` here. Results whose source or agent record is missing read as `offline`.

When `sort` is omitted or set to `relevance`, scores rounded to three decimal places define near-equal relevance groups. Within each group on the returned page, local and online-agent results come before unavailable-agent results. This does not hide results or reorder across pages. Explicit date, size, and name sorts are unchanged.

## Get a document

```http
GET /api/documents/{document_id}
```

Returns the full indexed document, including extracted content and metadata.

```bash
curl http://localhost:8000/api/documents/documents--abc123def456 \
  -H "Authorization: Bearer $TOKEN"
```

Document IDs come from search results. They use the source ID plus a path hash, so don't try to build them by hand unless you really need to.

## Preview endpoint

Readable previews and image/RAW previews are handled by:

```http
GET /api/documents/{document_id}/preview
```

Most users should use the web UI for previews, but this endpoint is available if you're building your own client.
