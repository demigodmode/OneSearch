# Upgrading

Guide for upgrading OneSearch to newer versions.

## Quick Upgrade

### Using Pre-built Images

```bash
# Pull latest image
docker compose pull

# Restart services
docker compose up -d
```

If your `docker-compose.yml` dates from 1.5.0 or earlier, this won't pick up a new release. See [Upgrading from 1.5.0 or earlier](#upgrading-from-150-or-earlier) first.

### Building from Source

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker build -t onesearch:dev .
ONESEARCH_IMAGE=onesearch:dev docker compose up -d
```

---

## Automatic Updates

OneSearch is compatible with Docker auto-update tools. Database migrations run automatically on startup, so updates can happen without manual intervention.

**Why it works:**
- Migrations run via `alembic upgrade head` in the entrypoint
- Healthchecks ensure the app is ready before marking the update successful
- Semver tags let you control update scope (patch, minor, major)

**Common tools:**

- **Watchtower** - Automatically pulls and updates containers on a schedule
- **Diun** - Sends notifications when new images are available (doesn't auto-update)
- **Ouroboros** - Similar to Watchtower
- **Custom scripts** - Cron jobs running `docker compose pull && docker compose up -d`

**Example with Watchtower:**

```bash
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  onesearch-app \
  --schedule "0 0 4 * * *"  # Daily at 4 AM
```

You can pin to specific tags if you want more control:
- `latest` - Always get the newest release
- `1.5` - Stay on the 1.5.x line
- `1.5.0` - Pin to a specific version (no auto-updates)

There is no major-only tag like `1`.

---

## Upgrading from 1.5.0 or earlier

The compose files changed after 1.5.0, so do this once.

**Replace your compose file.** Up to 1.5.0, `docker-compose.yml` and `docker-compose.legacy.yml` built OneSearch from source and had the published image commented out. With one of those files, `docker compose pull` has no OneSearch image to pull and you stay on the version you built. Download the current file and copy your own lines back into it, which is usually just the source mounts under `volumes:`:

```bash
cp docker-compose.yml docker-compose.yml.bak
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
# copy your source mounts over from docker-compose.yml.bak, then:
docker compose pull
docker compose up -d
```

Check which setup you have before downloading. If your current file has a separate `meilisearch` service, you're on the two-container setup, and the file to download is `docker-compose.legacy.yml`. Replacing it with the default `docker-compose.yml` would switch you to managed Meilisearch, which needs the [migration](migrate-to-managed-meilisearch.md). Your data is safe either way: the `onesearch_data`, `onesearch_index` and `meilisearch_data` volumes keep their names.

**If you used `docker-compose.managed-meili.yml`,** switch to `docker-compose.yml`. The two were identical and the copy has been removed.

**Check your `.env` for old values.** Settings such as `ALLOWED_SOURCE_PATHS`, `SCHEDULE_TIMEZONE` and the size limits used to be ignored when set in `.env`. They take effect now.

**Check schedules that use weekday numbers.** The **Weekly (Sunday 2:00 AM)** preset and advanced cron like `0 2 * * 1-5` ran one day late before. They now run on the days they say. Weekday names (`mon-fri`, `sun`) are unchanged.

**Reindex sources with audio or video.** The image now has `ffprobe`, so a full reindex adds tags, duration and codec details to media files that were indexed by filename only.

---

## v1.0.0: managed Meilisearch is the default setup

New installs use a single OneSearch container with managed Meilisearch. Existing two-container installs keep working; do not overwrite your existing compose file unless you intend to migrate.

If you want to migrate, back up your compose/env files, keep the OneSearch data volume mounted at `/app/data`, add the managed index volume at `/app/meili_data`, and run a full reindex for each source after startup.

If you want to stay on the two-container setup, use `docker-compose.legacy.yml`. That mode is still supported for existing installs and advanced deployments, but you manage Meilisearch version compatibility yourself.

The search index is derived from your configured sources, so it can be rebuilt if needed. The source files and OneSearch database are the important data to preserve. For the step-by-step flow, see [Migrating to managed Meilisearch](migrate-to-managed-meilisearch.md).

---

## Version-Specific Notes

Check the [Changelog](../about/changelog.md) for breaking changes and migration notes.
