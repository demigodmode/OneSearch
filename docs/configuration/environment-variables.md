# Environment Variables

OneSearch is configured through environment variables, typically set in a `.env` file.

## Required Variables

### MEILI_MASTER_KEY

**Required**

The master key for the managed or external Meilisearch instance. This protects the search API.

Generate a secure key:

```bash
# Linux/macOS
openssl rand -base64 32

# Windows PowerShell
-join (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

Example:
```env
MEILI_MASTER_KEY=your-generated-key-here
```

**Important:** Keep this secure. Don't commit it to version control. Use different keys for different deployments.

---

## Optional Variables

### Database

**DATABASE_URL**

SQLite database path.

- Default: `sqlite:////app/data/onesearch.db`
- Example: `sqlite:////app/data/onesearch.db`

The database stores source configurations and file metadata for incremental indexing.

### Meilisearch

**ONESEARCH_MANAGED_MEILI**

Whether OneSearch starts the bundled Meilisearch process inside the app container.

- Default Docker quickstart: `true`
- Options: `true`, `false`

For the default Docker install, leave `ONESEARCH_MANAGED_MEILI=true` and do not set `MEILI_URL`. OneSearch starts Meilisearch on `127.0.0.1:7700` and points the backend at it internally.

**MEILI_URL**

Meilisearch endpoint for external Meilisearch mode.

- Required only when `ONESEARCH_MANAGED_MEILI=false`
- Legacy compose example: `http://meilisearch:7700`

If you use `docker-compose.legacy.yml`, set `MEILI_URL=http://meilisearch:7700` or point it at your own Meilisearch instance. External-mode users manage Meilisearch version compatibility themselves.

### Deployment Access

**CORS_ORIGINS**

Comma-separated list of browser origins allowed to call the API.

- Default: localhost development origins (`http://localhost:5173`, `http://localhost:8000`)
- Example: `https://search.example.com,https://files.example.com`

Most Docker installs behind the bundled nginx do not need to set this. Set it when you host the frontend/API behind a different domain or reverse proxy.

**ALLOWED_SOURCE_PATHS**

Comma-separated parent directories that sources must live under.

- Default: `/data`
- Example: `/data,/mnt/media`

This is a safety guard. If you try to add a source outside these paths, the API rejects it before indexing. In Docker, make sure this matches the container paths you mount, not host paths.

### Runtime User and Mounted Volumes

**PUID** / **PGID**

UID and GID used by the OneSearch backend process inside the container.

- Default: `1000` / `1000`
- Example: `PUID=1001`, `PGID=100`

Set these when your source directories are readable by a specific host user or shared group, especially on NAS, SMB/NFS, or homelab setups. OneSearch adjusts the internal `onesearch` user at startup, then runs the backend and managed Meilisearch as that identity.

The IDs must be numeric. The container still needs write access to `/app/data` and, in managed mode, `/app/meili_data`.

### Logging

**LOG_LEVEL**

Logging verbosity.

- Default: `INFO`
- Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`

Use `DEBUG` for troubleshooting, `INFO` for normal operation, `WARNING` or `ERROR` for production.

### File Size Limits

These control which files get indexed based on size.

**MAX_TEXT_FILE_SIZE_MB**

Maximum size for text files (txt, log, conf, etc.)

- Default: `10`
- Unit: Megabytes

Files larger than this are skipped with a warning.

**MAX_PDF_FILE_SIZE_MB**

Maximum size for PDF files.

- Default: `50`
- Unit: Megabytes

Large PDFs can take a long time to process. Adjust based on your needs and performance.

**MAX_OFFICE_FILE_SIZE_MB**

Maximum size for Office files (docx, xlsx, pptx).

- Default: `50`
- Unit: Megabytes

### Rich Media Defaults

Most rich media behavior can also be changed in Admin → Settings. Environment variables set the defaults used before an app setting is saved.

**UNSUPPORTED_FILE_POLICY**

What to do with unknown file types.

- Default: `metadata_only`
- Options: `metadata_only`, `skip`

**MEDIA_METADATA_MODE**

Whether audio/video files are probed with `ffprobe` when available.

- Default: `auto`
- Options: `auto`, `off`

**RAW_METADATA_MODE**

Whether RAW photos are probed with `exiftool` when available.

- Default: `auto`
- Options: `auto`, `off`

**RAW_METADATA_TIMEOUT_SECONDS**

Timeout for `exiftool` RAW metadata probing.

- Default: `10`
- Unit: Seconds

**INDEX_GPS_METADATA**

Whether GPS metadata from photos is indexed.

- Default: `false`
- Options: `true`, `false`

**SHOW_PREVIEWS**

Whether document image previews are enabled.

- Default: `true`
- Options: `true`, `false`

**RAW_PREVIEW_ENABLED**

Whether OneSearch extracts embedded JPEG previews from RAW photos on demand.

- Default: `true`
- Options: `true`, `false`

**MAX_PREVIEW_SIZE_MB**

Maximum source file size for image/RAW previews.

- Default: `50`
- Options: `25`, `50`, `100`

**MEDIA_PROBE_MAX_SIZE_MB**

Maximum media file size for ffprobe metadata extraction. `0` means unlimited; the extraction timeout still applies.

- Default: `0`
- Unit: Megabytes

**IMAGE_METADATA_MAX_SIZE_MB**

Maximum image/RAW file size for metadata extraction.

- Default: `100`
- Unit: Megabytes

**EPUB_EXTRACTION_MAX_SIZE_MB**

Maximum EPUB archive size for text extraction.

- Default: `100`
- Unit: Megabytes

**COMIC_EXTRACTION_MAX_SIZE_MB**

Maximum CBZ archive size for metadata/page-list extraction.

- Default: `100`
- Unit: Megabytes

**READABLE_PREVIEW_PAGE_CHARS**

Approximate generated page size for long readable previews.

- Default: `6000`
- Unit: Characters

**LONG_TEXT_PAGINATION_THRESHOLD_CHARS**

Plain text longer than this uses the paginated reader.

- Default: `20000`
- Unit: Characters

### Authentication

**SESSION_SECRET**

Secret key used for signing JWT tokens. If not set, a hardcoded fallback is used (fine for dev, but you'll want to set this in production).

- Default: hardcoded fallback (logs a warning)
- Example: `SESSION_SECRET=your-random-secret-here`

Generate one:

```bash
openssl rand -base64 32
```

**SESSION_EXPIRE_HOURS**

How long auth tokens stay valid.

- Default: `24`
- Unit: Hours

**AUTH_RATE_LIMIT**

Maximum failed login attempts per minute before requests get rejected.

- Default: `5`
- Unit: Attempts per minute

### Scheduling

**SCHEDULER_ENABLED**

Whether the background scheduler runs. Disable this if you only want manual indexing.

- Default: `true`
- Options: `true`, `false`

**SCHEDULE_TIMEZONE**

Timezone for cron schedule calculations.

- Default: `UTC`
- Example: `America/New_York`, `Europe/London`

Uses standard IANA timezone names.

### Extraction Timeouts

These prevent indexing from hanging on corrupt or problematic files.

**TEXT_EXTRACTION_TIMEOUT**

Timeout for text file extraction.

- Default: `5`
- Unit: Seconds

**PDF_EXTRACTION_TIMEOUT**

Timeout for PDF extraction.

- Default: `30`
- Unit: Seconds

PDF extraction is slower than text, so it gets a longer timeout.

**OFFICE_EXTRACTION_TIMEOUT**

Timeout for Office document extraction.

- Default: `30`
- Unit: Seconds

---

## Example .env File

```env
# Required
MEILI_MASTER_KEY=YourSecureRandomKeyHere123456789

# Optional - these show the defaults
DATABASE_URL=sqlite:////app/data/onesearch.db
ONESEARCH_MANAGED_MEILI=true
# MEILI_URL=http://meilisearch:7700  # Only for docker-compose.legacy.yml or another external Meilisearch instance
LOG_LEVEL=INFO
CORS_ORIGINS=
ALLOWED_SOURCE_PATHS=/data

# File size limits (in MB)
MAX_TEXT_FILE_SIZE_MB=10
MAX_PDF_FILE_SIZE_MB=50
MAX_OFFICE_FILE_SIZE_MB=50
IMAGE_METADATA_MAX_SIZE_MB=100
EPUB_EXTRACTION_MAX_SIZE_MB=100
COMIC_EXTRACTION_MAX_SIZE_MB=100

# Rich media behavior
UNSUPPORTED_FILE_POLICY=metadata_only
MEDIA_METADATA_MODE=auto
RAW_METADATA_MODE=auto
INDEX_GPS_METADATA=false
SHOW_PREVIEWS=true
RAW_PREVIEW_ENABLED=true
MAX_PREVIEW_SIZE_MB=50
MEDIA_PROBE_MAX_SIZE_MB=0
READABLE_PREVIEW_PAGE_CHARS=6000
LONG_TEXT_PAGINATION_THRESHOLD_CHARS=20000

# Extraction timeouts (in seconds)
TEXT_EXTRACTION_TIMEOUT=5
PDF_EXTRACTION_TIMEOUT=30
OFFICE_EXTRACTION_TIMEOUT=30
RAW_METADATA_TIMEOUT_SECONDS=10

# Authentication
SESSION_SECRET=YourSecureRandomSecretHere
SESSION_EXPIRE_HOURS=24
AUTH_RATE_LIMIT=5

# Scheduling
SCHEDULER_ENABLED=true
SCHEDULE_TIMEZONE=UTC
```

---

## Setting Environment Variables

### Docker Compose (Recommended)

Create a `.env` file in the same directory as `docker-compose.yml`:

```bash
cp .env.example .env
# Edit .env with your values
```

Docker Compose automatically loads variables from `.env`.

### Manual Export (Development)

When running the backend directly:

```bash
# Linux/macOS
export MEILI_MASTER_KEY=your-key
export LOG_LEVEL=DEBUG

# Windows PowerShell
$env:MEILI_MASTER_KEY="your-key"
$env:LOG_LEVEL="DEBUG"
```

### In Code

The backend loads variables in `backend/app/config.py` using Pydantic's `BaseSettings`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    meili_master_key: str
    database_url: str = "sqlite:////app/data/onesearch.db"
    log_level: str = "INFO"
    # ... etc
```

This validates types and provides defaults.

---

## Performance Tuning

### For Large Libraries

If you're indexing millions of files:

- Increase `MAX_PDF_FILE_SIZE_MB` cautiously - larger PDFs slow indexing
- Consider lowering `PDF_EXTRACTION_TIMEOUT` to skip problematic files faster
- Set `LOG_LEVEL=WARNING` to reduce log noise

### For Slow Systems

If indexing is too slow:

- Lower `MAX_PDF_FILE_SIZE_MB` to skip huge PDFs
- Reduce timeout values to fail faster on problematic files
- Use exclude patterns to skip unnecessary directories

### For Fast Systems

If you have powerful hardware:

- Increase file size limits to index more content
- Increase timeouts to handle complex documents

---

## Troubleshooting

### Meilisearch connection failed

For the default managed install, check that `ONESEARCH_MANAGED_MEILI=true` and `MEILI_MASTER_KEY` is set. For `docker-compose.legacy.yml` or another external Meilisearch instance, check that `MEILI_URL` points to the external service and that both containers use the same `MEILI_MASTER_KEY`.

### Files being skipped

Check file size limits. Files exceeding the max size are skipped and logged.

```bash
docker-compose logs -f onesearch | grep "exceeds"
```

### Extraction timeouts

If many files are timing out, either:
- Increase the timeout values
- Lower the file size limits to skip large files

---

## Security Notes

**Never commit `.env` to version control.** The `.env` file is in `.gitignore` by default.

**Use strong keys.** Generate random keys, don't use predictable values.

**Different keys per environment.** Use different `MEILI_MASTER_KEY` values for dev, staging, production.

---

## Next Steps

- [Docker Compose Configuration](docker-compose.md) - Configure Docker Compose
- [Performance Tuning](performance-tuning.md) - Optimize OneSearch
- [Volume Mounts](volume-mounts.md) - Mount source directories
