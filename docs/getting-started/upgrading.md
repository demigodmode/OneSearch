# Upgrading

Guide for upgrading OneSearch to newer versions.

## Quick Upgrade

### Using Pre-built Images

```bash
# Pull latest image
docker-compose pull

# Restart services
docker-compose up -d
```

### Building from Source

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose up -d --build
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
- **Custom scripts** - Cron jobs running `docker-compose pull && docker-compose up -d`

**Example with Watchtower:**

```bash
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  onesearch-app onesearch-meilisearch \
  --schedule "0 0 4 * * *"  # Daily at 4 AM
```

You can pin to specific tags if you want more control:
- `latest` - Always get the newest release
- `0.7` - Stay on the 0.7.x line (minor/patch updates only)
- `0.7.2` - Pin to a specific version (no auto-updates)

---

## Version-Specific Notes

Check the [Changelog](../about/changelog.md) for breaking changes and migration notes.
