# Sources API

Manage search sources via API. All endpoints require authentication.

## Endpoints

- `GET /api/sources` - List all sources
- `POST /api/sources` - Create source
- `GET /api/sources/{id}` - Get source details
- `PUT /api/sources/{id}` - Update source
- `DELETE /api/sources/{id}` - Delete source
- `POST /api/sources/{id}/reindex` - Trigger reindex

## Source Fields

When creating or updating a source, you can set:

- `name` - Display name for the source
- `root_path` - Directory path to index (container path in Docker)
- `include_patterns` - Glob patterns for files to include (comma-separated)
- `exclude_patterns` - Glob patterns for files to exclude (comma-separated)
- `scan_schedule` - Cron schedule for automatic indexing (optional)

The `scan_schedule` field accepts presets (`@hourly`, `@daily`, `@weekly`) or standard cron expressions (e.g., `0 */6 * * *` for every 6 hours). Set to `null` or omit for manual-only indexing.

Response objects also include `last_scan_at` and `next_scan_at` timestamps.

## Reindex

`POST /api/sources/{id}/reindex` triggers an immediate reindex. Add `?full=true` for a full reindex instead of incremental.

Returns `409 Conflict` if the source is already being indexed (either by a manual trigger or a scheduled run).

See [API Overview](index.md#quick-examples) for examples.

Or visit the interactive docs: http://localhost:8000/docs
