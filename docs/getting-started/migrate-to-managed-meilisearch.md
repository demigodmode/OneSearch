# Migrating to managed Meilisearch

Managed Meilisearch runs the search engine inside the OneSearch app container. The regular two-container setup still works, so there is no rush to switch existing installs.

Use this guide if you want to try the managed mode introduced in v0.13.

## Before you start

A few things to know:

- Keep your original source files exactly where they are.
- Keep your OneSearch data volume. This contains the SQLite database and source configuration.
- The Meilisearch index is rebuildable. If you switch modes, plan on reindexing your sources.
- External Meilisearch remains supported. You can roll back to the two-container compose file if needed.

## 1. Back up the current install

From the directory with your current `docker-compose.yml` and `.env`:

```bash
docker-compose down
```

Back up the compose/env files:

```bash
cp docker-compose.yml docker-compose.external-meili.backup.yml
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

## 2. Download the managed compose file

```bash
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.managed-meili.yml
```

If you are running from a git checkout, the file is already in the repo.

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

copy the source mounts into the `onesearch` service in `docker-compose.managed-meili.yml`:

```yaml
volumes:
  - onesearch_data:/app/data
  - onesearch_index:/app/meili_data
  - /mnt/nas/documents:/data/documents:ro
```

Keep source mounts read-only unless you have a specific reason not to.

## 5. Start managed mode

```bash
docker-compose -f docker-compose.managed-meili.yml up -d
```

Check the container status:

```bash
docker-compose -f docker-compose.managed-meili.yml ps
```

Follow logs during the first start:

```bash
docker-compose -f docker-compose.managed-meili.yml logs -f onesearch
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

## 7. Reindex sources

After switching modes, reindex your sources from the admin UI. The source configuration is kept in OneSearch's database, but the managed Meilisearch index starts with its own `/app/meili_data` volume.

Large source trees may take a while to rebuild. Your original files are not modified.

## Rolling back

If managed mode does not work for your setup:

```bash
docker-compose -f docker-compose.managed-meili.yml down
```

Start the previous two-container setup again:

```bash
docker-compose -f docker-compose.external-meili.backup.yml up -d
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
