# Docker Compose Configuration

The default `docker-compose.yml` runs OneSearch as one container with managed Meilisearch inside it. That is the recommended setup for new installs.

## Service shape

The default service exposes one port:

```yaml
ports:
  - "8000:8000"
```

That serves the web UI, API, and FastAPI docs:

- `http://localhost:8000`
- `http://localhost:8000/api`
- `http://localhost:8000/docs`

## Image vs local build

For local development, the compose file builds from the repo:

```yaml
build:
  context: .
  dockerfile: Dockerfile
```

For a normal install, use the published image and remove or comment out `build`:

```yaml
image: ghcr.io/demigodmode/onesearch:latest
```

## Required environment

At minimum, set these in `.env`:

```env
MEILI_MASTER_KEY=your-generated-key-here
SESSION_SECRET=your-session-secret-key-here
```

`MEILI_MASTER_KEY` protects the search engine. `SESSION_SECRET` signs login tokens.

## Volumes

The default managed setup uses two named volumes:

```yaml
volumes:
  - onesearch_data:/app/data
  - onesearch_index:/app/meili_data
```

`onesearch_data` stores the SQLite database and app data. `onesearch_index` stores the managed Meilisearch index.

Mount your files separately, preferably read-only:

```yaml
volumes:
  - onesearch_data:/app/data
  - onesearch_index:/app/meili_data
  - /home/alex/Documents:/data/documents:ro
  - /mnt/nas/photos:/data/photos:ro
```

When adding sources, use `/data/documents` and `/data/photos`, not the host paths. The source form's **Test** button can confirm whether OneSearch can see and read the path before you save it.

See [Volume Mounts](volume-mounts.md) for more examples. If you run with Podman, also see [Podman](podman.md) for rootless and SELinux notes.

## Legacy external Meilisearch

Existing two-container installs can keep using `docker-compose.legacy.yml`.

Use that when you want to run Meilisearch as a separate service or point OneSearch at your own Meilisearch instance:

```bash
docker compose -f docker-compose.legacy.yml up -d
```

For new installs, stick with the default managed compose file unless you have a reason not to.

## After editing compose

After changing ports, environment, or mounts:

```bash
docker compose up -d
```

If you added new source mounts, add or update the matching source path in the web UI. If you changed what a source can see, run a reindex.
