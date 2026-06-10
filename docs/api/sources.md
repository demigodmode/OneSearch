# Sources API

Manage search sources via API. All endpoints require authentication.

## Endpoints

- `GET /api/sources` - List all sources
- `POST /api/sources` - Create source
- `GET /api/sources/{id}` - Get source details
- `PUT /api/sources/{id}` - Update source
- `DELETE /api/sources/{id}` - Delete source
- `POST /api/sources/test-path` - Test a candidate root path before saving
- `POST /api/sources/{id}/reindex` - Trigger reindex
- `POST /api/sources/{id}/clear-stale` - Remove stale failed-file entries

## Source Fields

When creating or updating a source, you can set:

- `id` - Optional source ID on create. If omitted, OneSearch generates one from the name.
- `name` - Display name for the source
- `root_path` - Directory path to index (container path in Docker)
- `include_patterns` - Array of glob patterns for files to include
- `exclude_patterns` - Array of glob patterns for files to exclude
- `scan_schedule` - Cron schedule for automatic indexing (optional)

The `scan_schedule` field accepts presets (`@hourly`, `@daily`, `@weekly`) or standard five-field cron expressions (e.g., `0 */6 * * *` for every 6 hours on cron clock boundaries). Set to `null` or omit for manual-only indexing. The web UI's friendly interval controls save cron expressions into this same field.

Response objects also include `created_at`, `updated_at`, `last_scan_at`, and `next_scan_at` timestamps.

Example create body:

```json
{
  "name": "Documents",
  "root_path": "/data/documents",
  "include_patterns": ["**/*.pdf", "**/*.md"],
  "exclude_patterns": ["**/.git/**", "**/node_modules/**"],
  "scan_schedule": "@daily"
}
```

The CLI and web UI accept comma-separated pattern text. The API takes arrays.

## Test a source path

`POST /api/sources/test-path` checks a candidate root path without saving it.

```bash
curl -X POST http://localhost:8000/api/sources/test-path \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"root_path": "/data/documents"}'
```

Example response:

```json
{
  "path": "/data/documents",
  "ok": true,
  "exists": true,
  "is_directory": true,
  "readable": true,
  "inside_allowed_roots": true,
  "allowed_roots": ["/data"],
  "looks_like_host_path": false,
  "message": "Path is ready to use.",
  "hint": null
}
```

Use this for Docker/Podman mount troubleshooting before creating or updating a source. It can also flag host-looking paths such as Windows drive paths or common Linux host paths that are not visible inside the container.

## Reindex

`POST /api/sources/{id}/reindex` triggers an immediate reindex. Add `?full=true` for a full reindex instead of incremental.

Returns `409 Conflict` if the source is already being indexed (either by a manual trigger or a scheduled run).

## Clear stale failed files

`POST /api/sources/{id}/clear-stale` removes failed entries for files that no longer exist on disk. This is useful after moving or deleting files that were already listed as failures.

```bash
curl -X POST http://localhost:8000/api/sources/documents/clear-stale \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "cleared": 3
}
```

See [API Overview](index.md#quick-examples) for examples.

Or visit the interactive docs: http://localhost:8000/docs
