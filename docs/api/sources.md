# Sources API

Manage search sources via API. All endpoints require authentication.

## Endpoints

- `GET /api/sources` - List all sources
- `POST /api/sources` - Create source
- `GET /api/sources/{id}` - Get source details
- `PUT /api/sources/{id}` - Update source
- `DELETE /api/sources/{id}` - Delete source
- `POST /api/sources/test-path` - Test a candidate root path before saving
- `GET /api/sources/test-path/{job_id}` - Read a queued remote path test
- `GET /api/sources/local-roots` - List configured local roots the folder picker can browse
- `POST /api/sources/browse-local` - List subfolders under a local root
- `POST /api/sources/{id}/reindex` - Trigger reindex
- `POST /api/sources/{id}/clear-stale` - Clean failed-file entries
- `POST /api/sources/batches` - Save a batch of up to 25 source requests
- `GET /api/sources/batches` - List your saved batches
- `GET /api/sources/batches/{batch_id}` - Read a saved batch and its item results
- `POST /api/sources/batches/{batch_id}/items/{item_id}/create` - Create or retry one item
- `POST /api/sources/batches/{batch_id}/dismiss` - Hide a batch from the Sources page

## Source Fields

When creating or updating a source, you can set:

- `id` - Optional source ID on create. Letters, numbers, hyphens and underscores only, up to 100 characters; anything else is rejected with `422`. If omitted, OneSearch generates one from the name. An ID that's already taken returns `400`.
- `name` - Display name for the source
- `root_path` - Directory path to index (container path in Docker)
- `location_type` - `"local"` (default) or `"agent"`
- `agent_id` - Agent ID for a remote source; `null` for a local source
- `processing_mode` - `"on_agent"`, `"on_server"`, or `null` to inherit the agent default; only applies to remote sources
- `path_validation_job_id` - Successful remote path-test job ID, required when creating a remote source or changing its agent or path
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

`GET /api/sources` also fills in the read-only `agent_name` and `agent_status` fields for remote sources. `agent_status` is `online`, `offline`, `disabled`, or `revoked`, computed from heartbeat freshness, access state, and the global Remote agents setting. A degraded but connected agent counts as `online`; a missing agent counts as `offline`. Both fields are `null` for local sources. The single-source, create, and update responses currently leave these fields `null`; use the list endpoint for availability, not those response defaults.

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

### Remote path validation

Enable remote agents and enroll and approve the agent first. It must be online for a path test. Send `location_type: "agent"`, its `agent_id`, and the proposed `root_path` to `POST /api/sources/test-path`. Use the agent machine's path syntax, or container paths for a Docker agent. The path must be at or below one of its advertised allowed roots.

The response includes a `job_id` and starts with `ok: false` while validation is queued. Poll `GET /api/sources/test-path/{job_id}` until `status` is `completed` and `ok` is `true`. A pending response is not a failed path check. If the job fails or is cancelled, correct the problem and start a new test.

Pass that job ID as `path_validation_job_id` when creating the remote source. The validation must have completed within the last 10 minutes and match the same agent and path. Changing a source to a remote location, selecting a different agent, or changing its remote path requires a matching validation too. Editing only the name, patterns, or schedule does not require a new path test.

Missing validation on save returns `422`; an unknown validation job returns `404`. An incomplete, expired, or mismatched validation returns `409`. Run a fresh test before retrying. See [Remote agents](agents.md) for enrollment and approval.

## Browse local folders

`GET /api/sources/local-roots` lists the roots from `ALLOWED_SOURCE_PATHS` that the folder picker can browse.

```bash
curl http://localhost:8000/api/sources/local-roots \
  -H "Authorization: Bearer $TOKEN"
```

Example response:

```json
{
  "browse_available": true,
  "roots": [
    {"root_id": "local-3f2a9c1be04d", "path": "/data", "label": "/data"}
  ]
}
```

`root_id` is derived from the path and stays stable even if `ALLOWED_SOURCE_PATHS` is reordered. If `ALLOWED_SOURCE_PATHS` is empty, this returns `{"browse_available": false, "roots": []}`.

`POST /api/sources/browse-local` lists the folders directly under a root, or under a subfolder of it.

```bash
curl -X POST http://localhost:8000/api/sources/browse-local \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"root_id": "local-3f2a9c1be04d", "path": "photos/2024"}'
```

`path` is relative to the root; use `""` to list the root itself. Example response:

```json
{
  "root_id": "local-3f2a9c1be04d",
  "path": "photos/2024",
  "entries": [
    {"name": "vacation", "path": "photos/2024/vacation"}
  ],
  "truncated": false
}
```

Only folders are listed, capped at 500 per directory; `truncated` is `true` when there were more. Symlinked folders are left out of the listing. Errors come back as `detail: {code, message}`:

| Status | Code | Meaning |
|--------|------|---------|
| 409 | `local_browse_unavailable` | `ALLOWED_SOURCE_PATHS` is empty, so there's nothing to browse |
| 422 | `local_root_unknown` | `root_id` doesn't match a currently configured root |
| 422 | `browse_path_invalid` | `path` contains `..`, is absolute, uses backslashes, or has control characters |
| 409 | `browse_path_unavailable` | the folder is missing, not a directory, unreadable, or a symlink along the way; these all return the same response on purpose |

## Create sources in a batch

`POST /api/sources/batches` saves one request for 1 to 25 local folders or folders on one agent. It does not create the sources yet. Supply a new UUID v4 for the batch and each item. Each item has its own name and path; `common_settings` applies to all items. The normalized request must fit within 64 KiB. The server keeps saved batches so you can resume after a lost response or page reload.

```json
{
  "id": "914b176f-988b-44ea-bb9b-20ac87cd5b31",
  "location_type": "local",
  "agent_id": null,
  "common_settings": {"use_default_schedule": true},
  "items": [
    {"id": "ae48c19a-5623-42c3-a264-c384cb54ebad", "name": "Books", "root_path": "/data/books"},
    {"id": "818652c2-9a34-4ccd-9c12-885e976dc311", "name": "Photos", "root_path": "/data/photos"}
  ]
}
```

The create request returns `201` with the saved batch and items in `pending` state. Repeating the same batch ID with the same request returns its saved state; changing the request for an existing ID returns `409`. A batch ID owned by another user returns `404`. IDs remain reserved, even if an owner or source is deleted.

Call `POST /api/sources/batches/{batch_id}/items/{item_id}/create` for each pending item with `{}` as the body. For an agent item, first run a fresh remote path test and pass `{"path_validation_job_id": "..."}`. The agent must be online for that test. The item response has `state`, `source_id`, `source_deleted`, `duplicate_of_item_id`, `error`, and `updated_at`. Possible states are:

| State | Meaning |
| --- | --- |
| `created` | This item created a source. |
| `already_exists` | A source at the same canonical local path, or the same path and agent, already exists. |
| `duplicate_selection` | An earlier item in this batch selected the same location. |
| `failed` | Fix the reported path or agent condition before retrying. The saved request cannot be edited. |
| `pending` | This item has not finished. |

Local duplicates use the resolved path. Remote duplicates use the agent ID and normalized path; Windows agent paths compare without case. Parent and child paths are separate locations. Successful item outcomes remain saved, so repeating the item request does not create another source. A failed item can be retried after fixing the reported condition. To change its saved path, start a new batch. A deleted source is shown with `source_deleted: true`; retrying its saved successful item does not recreate it. If the response to the initial batch request is lost, list your batches before starting a new ID.

`GET /api/sources/batches?limit=20` returns the current user's batches, newest first, with counts and a `next_cursor`. Pass that cursor to retrieve the next page. Page size is 1 to 20. `GET /api/sources/batches/{batch_id}` returns the item details. `POST /api/sources/batches/{batch_id}/dismiss` marks the batch as dismissed but retains its result and sources. Other users' batches return `404` on detail, item creation, and dismissal.

## Reindex

`POST /api/sources/{id}/reindex` triggers an immediate reindex. Add `?full=true` for a full reindex instead of incremental.

For a local source the request runs the reindex and returns `message` and `stats` when it finishes. For a remote-agent source it queues a job and returns `202` with `message`, `job_id`, `status` and `coalesced`.

Returns `409 Conflict` if the source is already being indexed (either by a manual trigger or a scheduled run), or if its agent is unavailable or remote agents are turned off.

## Delete

`DELETE /api/sources/{id}` returns `204` with no body, or `404` if the source doesn't exist. If the documents can't be removed from the search index it returns `502` and leaves the source in place, so you can try again.

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
