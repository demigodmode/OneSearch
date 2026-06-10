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

### Building from Source

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build
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
- `1` - Stay on the 1.x line
- `1.1` - Stay on the 1.1.x line
- `1.1.0` - Pin to a specific version (no auto-updates)

---

## v1.0.0: managed Meilisearch is the default setup

New installs use a single OneSearch container with managed Meilisearch. Existing two-container installs keep working; do not overwrite your existing compose file unless you intend to migrate.

If you want to migrate, back up your compose/env files, keep the OneSearch data volume mounted at `/app/data`, add the managed index volume at `/app/meili_data`, and run a full reindex for each source after startup.

If you want to stay on the two-container setup, use `docker-compose.legacy.yml`. That mode is still supported for existing installs and advanced deployments, but you manage Meilisearch version compatibility yourself.

The search index is derived from your configured sources, so it can be rebuilt if needed. The source files and OneSearch database are the important data to preserve. For the step-by-step flow, see [Migrating to managed Meilisearch](migrate-to-managed-meilisearch.md).

---

## Version-Specific Notes

Check the [Changelog](../about/changelog.md) for breaking changes and migration notes.
