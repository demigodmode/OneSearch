# Migrating to managed Meilisearch

Managed Meilisearch runs the search engine inside the OneSearch app container and is the default for new OneSearch installs. The older two-container setup still works, so there is no rush to switch existing installs.

Use this guide if you already run the older two-container setup and want to migrate to the single-container managed setup. If your existing install is working and you want to keep Meilisearch separate, use `docker-compose.legacy.yml`.

## Before you start

A few things to know:

- Keep your original source files exactly where they are.
- Keep your OneSearch data volume. This contains the SQLite database and source configuration.
- The Meilisearch index is rebuildable. If you switch modes, plan on reindexing your sources.
- External Meilisearch remains supported. You can roll back to the two-container compose file if needed.

## 1. Back up the current install

From the directory with your current `docker-compose.yml` and `.env`:

```bash
docker compose down
```

Back up the compose/env files:

```bash
cp docker-compose.yml docker-compose.legacy.backup.yml
cp .env .env.backup
```

Back up named volumes if you use Docker volumes. The exact names depend on your compose project name, but these are common for the default setup:

```bash
docker volume ls | grep onesearch
```

At minimum, preserve the OneSearch app data volume mounted at `/app/data`. That is where the SQLite database lives.

If you want a simple archive backup and your volume is named `onesearch_onesearch_data`:

```bash
docker run --rm \
  -v onesearch_onesearch_data:/data:ro \
  -v "$PWD":/backup \
  alpine \
  tar -czf /backup/onesearch-data-backup.tar.gz -C /data .
```

You can also back up the old Meilisearch volume if you want to keep it around, but managed mode does not reuse the external container's `/meili_data` volume directly.

## 2. Download the current compose file

```bash
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
```

If you are running from a git checkout, the file is already in the repo. In v1.0 and later, `docker-compose.yml` is the managed Meilisearch setup.

## 3. Check `.env`

Make sure `.env` has these values set:

```env
MEILI_MASTER_KEY=your-secure-master-key-here
SESSION_SECRET=your-session-secret-key-here
DATABASE_URL=sqlite:////app/data/onesearch.db
```

You do not need to set `MEILI_URL` for managed mode. The app points itself at the bundled Meilisearch process.

## 4. Carry over source mounts

If your old `docker-compose.yml` had source mounts like this:

```yaml
volumes:
  - onesearch_data:/app/data
  - /mnt/nas/documents:/data/documents:ro
```

copy the source mounts into the `onesearch` service in the new `docker-compose.yml`:

```yaml
volumes:
  - onesearch_data:/app/data
  - onesearch_index:/app/meili_data
  - /mnt/nas/documents:/data/documents:ro
```

Keep source mounts read-only unless you have a specific reason not to.

## 5. Start managed mode

```bash
docker compose up -d
```

Check the container status:

```bash
docker compose ps
```

Follow logs during the first start:

```bash
docker compose logs -f onesearch
```

You should see OneSearch start, then managed Meilisearch become ready.

## 6. Verify the app

Open:

```text
http://localhost:8000
```

Or check health from the host:

```bash
curl http://localhost:8000/api/health
```

The health response should show Meilisearch as available.

## 7. Full reindex sources

After switching modes, run a full reindex for each source. Source configuration and indexed-file metadata are kept in OneSearch's SQLite database, but the managed Meilisearch index starts with its own `/app/meili_data` volume. A normal incremental reindex may skip unchanged files because SQLite still remembers them from the old index.

From the admin UI, go to **Admin → Sources** and use the **Full reindex** action for each source. Confirm the source path still exists inside the container before starting.

From the CLI, list sources and run full reindex per source:

```bash
onesearch source list
onesearch source reindex <source-id> --full
```

Or call the API directly:

```bash
curl -X POST \
  "http://localhost:8000/api/sources/<source-id>/reindex?full=true" \
  -H "Authorization: Bearer <token>"
```

Large source trees may take a while to rebuild. Your original files are not modified.

## Rolling back

If managed mode does not work for your setup:

```bash
docker compose down
```

Start the previous two-container setup again:

```bash
docker compose -f docker-compose.legacy.backup.yml up -d
```

If you did not change your old Meilisearch volume, the external setup should come back with the old index data.

## Cleaning up old Meilisearch data

Do not delete the old external Meilisearch volume until you are happy with managed mode and have confirmed search works after a restart.

When you are ready, find the old volume:

```bash
docker volume ls | grep meili
```

Then remove the old external Meilisearch volume by name:

```bash
docker volume rm <old-meilisearch-volume-name>
```

Do not remove the OneSearch data volume mounted at `/app/data` unless you want to reset the app.
