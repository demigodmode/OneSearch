# Environment Variables

OneSearch is configured through environment variables, typically set in a `.env` file.

## Required Variables

### MEILI_MASTER_KEY

**Required**

The master key for your Meilisearch instance. This protects the search API.

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

- Default: `sqlite:///data/onesearch.db`
- Example: `sqlite:///data/onesearch.db`

The database stores source configurations and file metadata for incremental indexing.

### Meilisearch

**MEILI_URL**

Meilisearch endpoint.

- Default: `http://meilisearch:7700`
- Example: `http://meilisearch:7700`

In Docker Compose, use the container name (`meilisearch`). If running Meilisearch separately, use the full URL.

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
DATABASE_URL=sqlite:///data/onesearch.db
MEILI_URL=http://meilisearch:7700
LOG_LEVEL=INFO

# File size limits (in MB)
MAX_TEXT_FILE_SIZE_MB=10
MAX_PDF_FILE_SIZE_MB=50
MAX_OFFICE_FILE_SIZE_MB=50

# Extraction timeouts (in seconds)
TEXT_EXTRACTION_TIMEOUT=5
PDF_EXTRACTION_TIMEOUT=30
OFFICE_EXTRACTION_TIMEOUT=30
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
    database_url: str = "sqlite:///data/onesearch.db"
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

Check that `MEILI_MASTER_KEY` matches in both the OneSearch and Meilisearch containers. Both need the same key.

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
