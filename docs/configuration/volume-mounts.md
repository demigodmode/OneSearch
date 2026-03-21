# Volume Mounts

OneSearch runs in Docker and can only index directories that are mounted into the container. This page covers the different ways to set that up and when to use each.

---

## How it works

When you add a source in the UI, you give it a **container path**: the path as seen from inside the Docker container, not the path on your host machine. So if you mount `/mnt/nas` → `/nas` in your compose file, you'd enter `/nas` (or a subdirectory like `/nas/documents`) when adding the source.

The mount has to exist before OneSearch starts. You can't add a path via the UI that hasn't been mounted. The container can't see it.

---

## Approaches

### Recommended: mount parent directories

Mount the top-level directories where your data lives, not the specific folders you want to index. This way you do the compose setup once, and the UI handles everything after that.

```yaml
services:
  onesearch:
    volumes:
      - onesearch_data:/app/data
      - /mnt/nas:/nas:ro
      - /mnt/external:/external:ro
```

Then in the UI you can add any subdirectory under those mounts (`/nas/documents`, `/nas/photos`, `/external/backups/archive`, etc.) without touching compose again.

Good fit for: NAS shares, external drives, organized data directories.

---

### Specific mounts

Mount exactly the paths you want to index, nothing more.

```yaml
services:
  onesearch:
    volumes:
      - onesearch_data:/app/data
      - /home/user/documents:/data/documents:ro
      - /mnt/nas/projects:/data/projects:ro
```

In the UI you'd add `/data/documents` and `/data/projects`. To add a new location later, you'd need to edit compose and restart.

Good fit for: tightly controlled setups, or if you want to be explicit about what the container can see.

---

### Full filesystem (advanced)

Mount your entire host filesystem into the container.

```yaml
services:
  onesearch:
    volumes:
      - onesearch_data:/app/data
      - /:/host:ro
```

Then add any path via the UI using the `/host/` prefix, e.g. `/host/mnt/nas/documents`.

This is the most flexible setup but means the container can read everything on your host. Fine for a single-user homelab where you trust what's running, but worth knowing before you do it.

---

## The `:ro` flag

All the examples above use `:ro` (read-only). OneSearch never modifies your files, so read-only is the right choice. It also means a bug or misconfiguration can't accidentally touch your data.

---

## Restarting after changes

Any time you add or change a volume mount in `docker-compose.yml`, you need to restart the stack for it to take effect:

```bash
docker-compose up -d
```

If you're using the [parent directory approach](#recommended-mount-parent-directories), you only have to do this once.
