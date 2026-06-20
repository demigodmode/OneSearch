# Preview API

The preview endpoint streams safe previews for indexed image documents. The same API also lets the web UI download original indexed files without buffering them in JavaScript first.

Authentication is required for previews and for creating download links.

## Endpoints

```http
GET  /api/documents/{document_id}/preview
POST /api/documents/{document_id}/download-link
GET  /api/documents/{document_id}/download?token=...
```

Use the document ID from a search result or from `GET /api/documents/{document_id}`.

```bash
curl -L http://localhost:8000/api/documents/documents--abc123def456/preview \
  -H "Authorization: Bearer $TOKEN" \
  --output preview.jpg
```

To download the original indexed file, first create a short-lived download link:

```bash
curl -X POST http://localhost:8000/api/documents/documents--abc123def456/download-link \
  -H "Authorization: Bearer $TOKEN"
```

The response includes a short-lived, document-scoped `url`. It is same-origin and relative, so clients should resolve it against the OneSearch base URL before opening it outside the browser:

```bash
curl -L "http://localhost:8000$DOWNLOAD_URL" --output original-file
```

Downloads validate that the indexed path still belongs to the configured source before streaming the file. They are not controlled by the preview on/off setting.

## Supported previews

The endpoint supports:

- browser-viewable images: JPG, PNG, WebP, GIF, TIFF
- RAW photos when an embedded JPEG preview is available

RAW previews do not decode sensor data. OneSearch scans for embedded JPEG previews and returns the best one it can find.

## Common errors

Preview and download errors return a structured `detail` object:

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
| `download_token_missing` | The download URL is missing its short-lived token. |
| `download_token_expired` | The download URL has expired. Create a new link. |
| `download_token_invalid` | The download token is malformed or not signed by this instance. |
| `download_token_wrong_document` | The download token is for a different document ID. |
| `raw_preview_disabled` | RAW previews are disabled. |
| `raw_preview_unavailable` | No embedded RAW preview could be extracted. |
| `unsupported_preview_type` | The document type does not have a streamed preview. |

## Settings

Preview behavior is controlled by the [Settings API](settings.md) and **Admin → Settings → File Previews**:

- `show_previews`
- `raw_preview_enabled`
- `max_preview_size_mb`
