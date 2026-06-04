# Understanding Indexing

Indexing is the scan-and-extract step that turns files into searchable documents.

A normal run does three things:

1. Walk the source directory.
2. Skip files that do not match the source patterns.
3. Extract text and metadata from new or changed files.

Deleted files are removed from the search index during the same pass.

## Incremental indexing

Reindexing is incremental by default. OneSearch tracks each file's path, modified time, size, and status. If a file has not changed, it is skipped.

That makes regular indexing cheap after the first scan. A big source might take a while the first time, then finish quickly on later runs.

Run it from the web UI with **Admin → Sources → Reindex**, or from the CLI:

```bash
onesearch source reindex documents
```

## Full reindex

A full reindex clears OneSearch's indexed metadata for that source and rebuilds it from disk.

Use it when:

- you changed indexing settings and want old documents refreshed
- you migrated Meilisearch data
- search results look stale or inconsistent
- an extractor changed and you want everything reprocessed

CLI:

```bash
onesearch source reindex documents --full
```

API:

```bash
curl -X POST "http://localhost:8000/api/sources/documents/reindex?full=true" \
  -H "Authorization: Bearer $TOKEN"
```

## What gets indexed

Supported formats get full text extraction where possible. PDFs, Office docs, Markdown, text, code, RTF, EPUB, subtitles, comics, images, RAW photos, and media files all have dedicated handling.

Unsupported files can still be indexed as metadata-only entries if **Admin → Settings → Indexing → Unsupported files** is set to metadata-only. That makes filenames and paths searchable even when OneSearch cannot read the file contents.

## Failures and skipped files

A failed file does not stop the whole source. OneSearch records the error and keeps going.

Common reasons:

- file is too large for the configured limit
- file disappeared while indexing was running
- extractor timed out
- file is corrupt or encrypted
- source mount is no longer available

Check **Admin → Status** for failed file details.

## Schedules

Sources can be manual-only or scheduled. Presets are hourly, daily, and weekly, with custom cron available if you need it.

Schedules run incremental indexing. If a source is already being indexed, another run for that source is skipped instead of running two scans at once.

See [Scheduling](scheduling.md) for cron examples.

!!! tip "Changing indexing settings"
    Settings such as unsupported-file behavior, RAW metadata extraction, GPS metadata, and extraction size limits apply to future indexing. Run a full reindex if existing documents need to be refreshed with new settings.
