# Performance Tuning

Most installs are fine with the defaults. Tune things only when you know what is slow: scanning, extraction, search, or storage.

## Start with source patterns

The cheapest speedup is not indexing junk.

Good excludes:

```text
**/.git/**,**/node_modules/**,**/__pycache__/**,**/dist/**,**/build/**
```

If a source only needs a few formats, use includes:

```text
**/*.pdf,**/*.docx,**/*.md,**/*.txt
```

## Storage matters

Put OneSearch data and the Meilisearch index on SSD storage if you can. Network storage is fine for source files, but it is slower to scan and can make first indexing runs take a while.

The default managed install stores app data in:

- `onesearch_data` for SQLite and app data
- `onesearch_index` for the managed Meilisearch index

## File size limits

Large files are where extraction gets expensive. Text, PDF, and Office limits can be changed in **Admin → Settings → Indexing**. The matching environment variables set their defaults before an app setting is saved:

```env
MAX_TEXT_FILE_SIZE_MB=10
MAX_PDF_FILE_SIZE_MB=50
MAX_OFFICE_FILE_SIZE_MB=50
IMAGE_METADATA_MAX_SIZE_MB=100
EPUB_EXTRACTION_MAX_SIZE_MB=100
COMIC_EXTRACTION_MAX_SIZE_MB=100
```

Lower the limits if indexing is getting stuck on giant files. Raise them only if you know those files are worth indexing, then use **Clean** or reindex affected sources.

## Rich media settings

RAW metadata uses `exiftool`; audio/video metadata uses `ffprobe` when available. Those probes are useful, but slower than plain filename metadata.

If media-heavy sources are slow, try:

- turn RAW metadata off in **Admin → Settings → Indexing**
- turn media metadata off in the same page
- keep GPS metadata disabled unless you need it
- reduce preview limits in **Admin → Settings → File Previews**

Run a full reindex if you want existing documents refreshed after changing indexing settings.

## Schedule heavy sources off-hours

Daily or weekly schedules are usually enough for NAS/photo/archive sources. Use custom cron if you want scans overnight:

```text
0 2 * * *
```

If a manual index is already running, a scheduled run for the same source is skipped rather than running twice.

## Batch size

`MEILISEARCH_BATCH_SIZE` controls how many documents are sent to Meilisearch at once. The default is `100`.

Bigger batches can be faster but use more memory. Smaller batches are gentler on low-memory boxes.
