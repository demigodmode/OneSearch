# Status & Health API

Monitor OneSearch system status. Status endpoints require authentication; the health endpoint does not.

## Endpoints

- `GET /api/health` - API health check (no auth required)
- `GET /api/status` - Overall indexing status
- `GET /api/status/{source_id}` - Source-specific status

## Status Response

The status response includes per-source details with scheduling information:

- `scan_schedule` — The source's cron schedule (e.g., `@daily`, `0 */6 * * *`), or `null` for manual-only
- `last_scan_at` — When the last scheduled or manual scan completed
- `next_scan_at` — When the next scheduled scan will run

## Example

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer your-token"
```

See [API Overview](index.md#quick-examples) for more examples.
