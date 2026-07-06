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
- `POST /api/sources/{id}/clear-stale` - Clean failed-file entries

## Source Fields

When creating or updating a source, you can set:

- `id` - Optional source ID on create. If omitted, OneSearch generates one from the name.
- `name` - Display name for the source
- `root_path` - Directory path to index (container path in Docker)
- `include_patterns` - Array of glob patterns for files to include
- `exclude_patterns` - Array of glob patterns for files to exclude
- `schedule_type` - `"cron"` or `"interval"` (default `"cron"`)
- `scan_schedule` - Cron schedule for automatic indexing (optional, used when `schedule_type` is `"cron"`)
- `interval_value` - Positive integer interval value (optional, used when `schedule_type` is `"interval"`)
- `interval_unit` - `"minutes"`, `"hours"`, or `"days"` (optional, used when `schedule_type` is `"interval"`)
- `use_default_schedule` - boolean. When `true`, the source ignores its own schedule fields and follows the global default schedule from [Settings](settings.md) instead.

When `schedule_type` is `"cron"`, `scan_schedule` accepts presets (`@hourly`, `@daily`, `@weekly`) or standard five-field cron expressions (e.g., `0 */6 * * *` for every 6 hours on cron clock boundaries). Set to `null` or omit for manual-only indexing.

When `schedule_type` is `"interval"`, the schedule is a true interval trigger, not a cron expression. "Every 6 hours" means 6 hours from when it's saved, not the next clock boundary. Both `interval_value` and `interval_unit` must be set together.

`use_default_schedule` and a source's own schedule fields aren't mutually exclusive in storage. The source's own schedule is preserved while `use_default_schedule` is `true`, and takes effect again as soon as it's turned back off.

Response objects also include `created_at`, `updated_at`, `last_scan_at`, `next_scan_at`, and `effective_schedule` (an object shaped like `{schedule_type, scan_schedule, interval_value, interval_unit}` describing the schedule actually driving the source right now, whether that's its own or the inherited default).

Example create body using a true interval:

```json
{
  "name": "Documents",
  "root_path": "/data/documents",
  "include_patterns": ["**/*.pdf", "**/*.md"],
  "exclude_patterns": ["**/.git/**", "**/node_modules/**"],
  "schedule_type": "interval",
  "interval_value": 6,
  "interval_unit": "hours"
}
```

Example create body following the global default instead:

```json
{
  "name": "Documents",
  "root_path": "/data/documents",
  "use_default_schedule": true
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

## Clean failed files

`POST /api/sources/{id}/clear-stale` cleans failed entries. Missing files are removed from tracking, while existing failed files are retried through the normal indexing path. Files that still fail remain in the failed list with their latest error.

```bash
curl -X POST http://localhost:8000/api/sources/documents/clear-stale \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "cleared": 1,
  "reindexed": 3,
  "still_failed": 0,
  "skipped": 0
}
```

See [API Overview](index.md#quick-examples) for examples.

Or visit the interactive docs: http://localhost:8000/docs
