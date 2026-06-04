# Settings API

The settings API manages app-level indexing, preview, and search defaults that are normally changed from **Admin → Settings**.

All settings endpoints require authentication.

## Endpoints

```http
GET /api/settings
PUT /api/settings
```

`GET` returns the effective settings: saved overrides plus environment-backed defaults.

`PUT` accepts a partial update. Send only the keys you want to change.

## Example

```bash
curl http://localhost:8000/api/settings \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl -X PUT http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "unsupported_file_policy": "metadata_only",
    "raw_metadata_mode": "off",
    "index_gps_metadata": false,
    "max_preview_size_mb": 50
  }'
```

## Fields

| Field | Values | Notes |
|-------|--------|-------|
| `unsupported_file_policy` | `metadata_only`, `skip` | Unknown file types can be searchable by filename/path or skipped. |
| `media_metadata_mode` | `auto`, `off` | Uses `ffprobe` when available. |
| `raw_metadata_mode` | `auto`, `off` | Uses `exiftool` when available. |
| `index_gps_metadata` | boolean | Off by default for privacy. |
| `show_previews` | boolean | Enables document/image preview endpoints. |
| `raw_preview_enabled` | boolean | Enables embedded JPEG previews for RAW photos. |
| `max_preview_size_mb` | `25`, `50`, `100` | Preview source file size limit. |
| `media_probe_max_size_mb` | integer | `0` means no size cap for media probing. Timeout still applies. |
| `image_metadata_max_size_mb` | integer | Image/RAW metadata extraction limit. |
| `epub_extraction_max_size_mb` | integer | EPUB extraction limit. |
| `comic_extraction_max_size_mb` | integer | CBZ extraction limit. |
| `readable_preview_page_chars` | integer | Approximate page size for long readable previews. |
| `long_text_pagination_threshold_chars` | integer | Text longer than this uses the paginated reader. |

## Reindexing after changes

Indexing settings affect future indexing. If you turn RAW metadata on or change unsupported-file behavior, run a full reindex for existing documents you want refreshed.
