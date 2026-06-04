# Monitoring

OneSearch does not need much babysitting, but there are a few places worth checking when something feels off.

## Web UI

Use **Admin → Status** for day-to-day monitoring.

It shows:

- backend/search health
- source count and document totals
- per-source indexed, skipped, and failed counts
- last index time
- failed file details when you expand a source

The page refreshes automatically during long indexing runs.

## Health endpoint

```http
GET /api/health
```

This endpoint does not require auth, so it works with Docker health checks and uptime monitors.

```bash
curl http://localhost:8000/api/health
```

A healthy response returns HTTP 200. If Meilisearch is unreachable, the endpoint returns HTTP 503 with a degraded status.

## Logs

For Docker installs:

```bash
docker compose logs -f onesearch
```

Useful things to look for:

- startup and migration messages
- Meilisearch connection warnings
- source path validation errors
- extractor failures during indexing
- scheduled indexing start/finish messages

Use `LOG_LEVEL=DEBUG` only while troubleshooting. Debug logs can include more request detail than you usually want in normal operation.

## Status from the CLI

```bash
onesearch health
onesearch status
onesearch status documents
```

Add `--json` if you want to feed the output into a script.

## Prometheus/Grafana

OneSearch does not expose Prometheus metrics today. For now, monitor the health endpoint, container status, logs, disk usage, and failed file counts.
