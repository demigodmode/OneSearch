# Status & Health API

Monitor OneSearch system status. Status endpoints require authentication; the health endpoint does not.

## Endpoints

- `GET /api/health` - API health check (no auth required)
- `GET /api/status` - Overall indexing status
- `GET /api/status/{source_id}` - Source-specific status

## Status Response

The status response includes per-source counts and scheduling information:

- `total_files`, `successful`, `failed`, `skipped`: indexed-file counts by status
- `failed_files`: up to 50 failed file details with path and error
- `last_indexed_at`: most recent indexed-file timestamp
- `scan_schedule`: the source's cron schedule (e.g., `@daily`, `0 */6 * * *`), or `null` for manual-only
- `last_scan_at`: when the last scheduled or manual scan completed
- `next_scan_at`: when the next scheduled scan will run

## Examples

Health check:

```bash
curl http://localhost:8000/api/health
```

Example healthy response:

```json
{
  "status": "healthy",
  "service": "onesearch-backend",
  "version": "1.1.0",
  "setup_required": false,
  "meilisearch": {
    "status": "available"
  }
}
```

Overall status:

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer your-token"
```

Example status response:

```json
{
  "sources": [
    {
      "source_id": "documents",
      "source_name": "Documents",
      "total_files": 120,
      "successful": 118,
      "failed": 2,
      "skipped": 0,
      "last_indexed_at": "2026-06-10T20:00:00",
      "scan_schedule": "0 */6 * * *",
      "last_scan_at": "2026-06-10T20:00:00",
      "next_scan_at": "2026-06-11T00:00:00",
      "failed_files": [
        {
          "path": "/data/documents/broken.pdf",
          "error": "PDF extraction timed out"
        }
      ]
    }
  ]
}
```

See [API Overview](index.md#quick-examples) for more examples.
