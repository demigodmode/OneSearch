# Preview API

The preview endpoint streams safe previews for indexed image documents. It is mainly used by the web UI, but custom clients can call it too.

Authentication is required.

## Endpoint

```http
GET /api/documents/{document_id}/preview
```

Use the document ID from a search result or from `GET /api/documents/{document_id}`.

```bash
curl -L http://localhost:8000/api/documents/documents--abc123def456/preview \
  -H "Authorization: Bearer $TOKEN" \
  --output preview.jpg
```

## Supported previews

The endpoint supports:

- browser-viewable images: JPG, PNG, WebP, GIF, TIFF
- RAW photos when an embedded JPEG preview is available

RAW previews do not decode sensor data. OneSearch scans for embedded JPEG previews and returns the best one it can find.

## Common errors

Preview errors return a structured `detail` object:

```json
{
  "detail": {
    "code": "preview_too_large",
    "message": "Preview file exceeds 50 MB limit"
  }
}
```

Common codes:

| Code | Meaning |
|------|---------|
| `previews_disabled` | Previews are disabled in settings. |
| `document_not_found` | No indexed document exists for that ID. |
| `source_not_found` | The document's source no longer exists. |
| `path_outside_source` | The indexed path is outside its configured source root. |
| `file_not_found` | The source file moved or was deleted after indexing. |
| `preview_too_large` | The source file is larger than the configured preview limit. |
| `raw_preview_disabled` | RAW previews are disabled. |
| `raw_preview_unavailable` | No embedded RAW preview could be extracted. |
| `unsupported_preview_type` | The document type does not have a streamed preview. |

## Settings

Preview behavior is controlled by the [Settings API](settings.md) and **Admin → Settings → File Previews**:

- `show_previews`
- `raw_preview_enabled`
- `max_preview_size_mb`
