# Troubleshooting

Most issues come down to mounts, secrets, or indexing failures. Start with logs and the status page.

## Check logs

```bash
docker compose logs -f onesearch
```

For startup problems, look for database migration errors, missing environment variables, or Meilisearch connection warnings.

## Container will not start

Check that `.env` exists and has at least:

```env
MEILI_MASTER_KEY=...
SESSION_SECRET=...
```

Then check the compose service:

```bash
docker compose ps
docker compose logs onesearch
```

If port 8000 is already in use, change the left side of the port mapping:

```yaml
ports:
  - "8080:8000"
```

Then open `http://localhost:8080`.

## Source path does not exist

In Docker, source paths are container paths.

If compose has:

```yaml
- /home/alex/Documents:/data/documents:ro
```

then the source path is `/data/documents`.

After changing mounts, restart:

```bash
docker compose up -d
```

## No search results

Check these in order:

1. Is the source added?
2. Did you run **Reindex**?
3. Does **Admin → Status** show successful files?
4. Are include patterns too narrow?
5. Are you filtering by the wrong source or type?
6. Are files failing because of size limits or extractor errors?

From the CLI:

```bash
onesearch status
onesearch status documents
```

## Indexing is slow

First indexing runs can be slow for PDFs, Office files, RAW photos, media files, and network mounts.

Things that help:

- exclude dependency/build folders
- use includes for sources that only need a few file types
- keep app/index volumes on SSD storage
- lower file size limits for huge files
- disable RAW/media metadata probing if you do not need it

See [Performance Tuning](../configuration/performance-tuning.md).

## Failed files stay in the status page

If the files were deleted or moved after scanning, use **Clear stale** on the status page for that source.

For deeper drift, run a full reindex:

```bash
onesearch source reindex documents --full
```

## Login stopped working

Tokens expire. Run:

```bash
onesearch login
```

If every token becomes invalid after restart, check that `SESSION_SECRET` is set and stable in `.env`.

## Health endpoint is degraded

```bash
curl http://localhost:8000/api/health
```

A degraded response usually means Meilisearch is not reachable. In the default managed setup, check the OneSearch container logs. In legacy external mode, also check the Meilisearch container.
