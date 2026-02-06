# First-Time Setup

After installing OneSearch, you'll go through a quick setup wizard, then you can add sources and start searching.

## Setup Wizard

When you first open OneSearch at http://localhost:8000, you'll be greeted by a setup wizard that asks you to create an admin account. Pick a username and password — this is what you'll use to log in going forward.

Once that's done, you're taken to the login page. Log in with the credentials you just created.

## Add a Source

A source is a directory that OneSearch will index. You can have multiple sources pointing to different locations.

### Using the Web UI

After logging in, click **Admin** in the top nav, then **Sources**.

Click **Add Source** and fill in:

- **Name**: Something descriptive like "Documents" or "NAS Files"
- **Path**: The container path to your files (e.g., `/data/documents`)
- **Include Patterns**: Which files to index (e.g., `**/*.pdf,**/*.md,**/*.txt`)
- **Exclude Patterns**: What to skip (optional, e.g., `**/node_modules/**,**/.git/**`)

Click **Add Source** and you're done.

**Important**: Use the container path, not your host path. If you mounted `/home/user/docs` to `/data/docs` in docker-compose.yml, use `/data/docs` here.

### Using the CLI

If you have the CLI installed:

```bash
onesearch source add "Documents" /data/documents --include "**/*.pdf,**/*.md"
```

Add `--no-validate` if the path only exists inside the Docker container.

### Using the API

First grab a token (see [Authentication](../administration/authentication.md)), then:

```bash
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Documents",
    "root_path": "/data/documents",
    "include_patterns": "**/*.pdf,**/*.md,**/*.txt"
  }'
```

---

## Index Your Files

Adding a source doesn't automatically index it unless you set up a schedule. You can trigger indexing manually or configure automatic scheduling.

### Web UI

Go to **Admin → Sources**, find your source, and click the **Reindex** button.

### CLI

```bash
onesearch source reindex documents
```

### API

```bash
curl -X POST http://localhost:8000/api/sources/documents/reindex \
  -H "Authorization: Bearer $TOKEN"
```

---

## Monitor Progress

Indexing large directories takes time, especially for PDFs and Office documents. Here's how to check progress:

### Web UI

Go to **Admin → Status** to see:

- Total documents indexed across all sources
- Per-source breakdowns
- Any files that failed to index (click to expand and see errors)

The page auto-refreshes every 30 seconds.

### CLI

```bash
onesearch status
```

Or for a specific source:

```bash
onesearch status documents
```

### API

```bash
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## Search

Once indexing completes (or even while it's running), you can search.

### Web UI

Go to the home page and type a query. Meilisearch handles typos well, so don't worry about exact matches.

Use the filters on the left to narrow by source or file type. Click any result card to see the full document with syntax highlighting.

Press `Cmd+K` (Mac) or `Ctrl+K` (Windows) to focus the search box from anywhere.

### CLI

```bash
onesearch search "kubernetes"
```

Filter by source:

```bash
onesearch search "docker" --source documents
```

Filter by type:

```bash
onesearch search "readme" --type md
```

### API

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"q": "kubernetes", "limit": 10}'
```

---

## Include/Exclude Patterns

Patterns use glob syntax to match file paths. Here are common patterns:

### Include Examples

| Pattern | Matches |
|---------|---------|
| `**/*.pdf` | All PDFs in any directory |
| `**/*.{md,txt}` | All Markdown and text files |
| `*.log` | Log files in root only |
| `docs/**/*` | Everything under docs/ |

### Exclude Examples

| Pattern | Skips |
|---------|-------|
| `**/node_modules/**` | Node.js dependencies |
| `**/.git/**` | Git repository data |
| `**/__pycache__/**` | Python cache |
| `**/.*` | Hidden files |

Separate multiple patterns with commas: `**/*.pdf,**/*.md,**/*.txt`

---

## Incremental vs Full Reindex

By default, reindexing is incremental. OneSearch checks each file's modified time and size. If nothing changed, it skips the file. This makes regular updates fast.

Sometimes you want a full reindex:

- After changing extractors or indexing logic
- Recovering from errors
- Debugging search issues

**Web UI**: Check the "Full reindex" box when clicking Reindex.

**CLI**: Add `--full`:

```bash
onesearch source reindex documents --full
```

**API**: Add `?full=true`:

```bash
curl -X POST "http://localhost:8000/api/sources/documents/reindex?full=true" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Troubleshooting

### Source path doesn't exist

Error: `Source path does not exist: /data/documents`

Make sure you mounted the directory in docker-compose.yml:

```yaml
volumes:
  - /host/path:/data/documents:ro
```

Restart after adding mounts:

```bash
docker-compose down && docker-compose up -d
```

### No search results

Possible causes:

1. Indexing isn't done yet - check the status page
2. Your include patterns don't match any files
3. Files failed to index - check the failed files list on the status page

### Indexing is slow

Network mounts (NAS over SMB/NFS) are slower than local storage. Large PDFs take longer to process than text files. Check the logs if it seems stuck:

```bash
docker-compose logs -f onesearch
```

---

## Set Up a Schedule (Optional)

Instead of manually triggering reindex every time, you can set up automatic schedules. When adding or editing a source, pick a preset (Hourly, Daily, Weekly) or enter a custom cron expression.

See [Scheduling](../user-guide/scheduling.md) for more details.

---

## Next Steps

Now that you have OneSearch running:

- [Learn more about searching](../user-guide/searching.md)
- [Explore the web interface](../user-guide/web-interface.md)
- [Add more sources](../user-guide/adding-sources.md)
- [Set up scan schedules](../user-guide/scheduling.md)
- [Install the CLI](../cli/installation.md)
- [Explore the API](../api/index.md)

Need help? Check the [Troubleshooting Guide](../administration/troubleshooting.md) or [open an issue on GitHub](https://github.com/demigodmode/OneSearch/issues).
