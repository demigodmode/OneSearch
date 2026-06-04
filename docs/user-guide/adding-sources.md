# Adding Sources

A source is a directory OneSearch is allowed to scan. Most installs have a few: documents, notes, photos, maybe a NAS mount.

## The path is the container path

In Docker, OneSearch only sees paths mounted into the container. If your compose file has this:

```yaml
volumes:
  - /home/alex/Documents:/data/documents:ro
```

then the source path is:

```text
/data/documents
```

not `/home/alex/Documents`.

The `:ro` part is recommended. OneSearch only needs to read your files.

## Add a source in the web UI

Go to **Admin → Sources**, click **Add Source**, then fill in:

- **Name**: something you recognize later, like `Documents` or `NAS Photos`
- **Path**: the container path, such as `/data/documents`
- **Include patterns**: optional comma-separated globs
- **Exclude patterns**: optional comma-separated globs
- **Schedule**: manual, hourly, daily, weekly, or custom cron

After saving, run a reindex from the same page unless you set a schedule and are happy to wait for the next run.

## Add a source with the CLI

```bash
onesearch source add "Documents" /data/documents
```

With patterns:

```bash
onesearch source add "Notes" /data/notes \
  --include "**/*.md,**/*.txt" \
  --exclude "**/.git/**,**/node_modules/**"
```

If the path exists only inside Docker, your local CLI machine may not be able to validate it. Use:

```bash
onesearch source add "Documents" /data/documents --no-validate
```

## Add a source with the API

```bash
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Documents",
    "root_path": "/data/documents",
    "include_patterns": ["**/*.pdf", "**/*.md", "**/*.txt"],
    "exclude_patterns": ["**/.git/**", "**/node_modules/**"],
    "scan_schedule": "@daily"
  }'
```

`include_patterns` and `exclude_patterns` are arrays in the API. The CLI and web UI accept comma-separated text and convert it for you.

## Pattern examples

| Pattern | What it does |
|---------|--------------|
| `**/*.pdf` | all PDFs below the source root |
| `**/*.{md,txt}` | Markdown and text files |
| `docs/**/*` | everything under a `docs` folder |
| `**/.git/**` | skip Git internals |
| `**/node_modules/**` | skip Node dependencies |
| `**/__pycache__/**` | skip Python cache directories |

If you leave includes empty, OneSearch scans everything it supports. Default excludes already skip common dependency/build folders when no custom excludes are provided.

## Changing a source

Editing the path or patterns affects future indexing. If you want old indexed documents cleaned up immediately, run a reindex after saving. Use a full reindex if the old settings indexed a lot of things you no longer want.
