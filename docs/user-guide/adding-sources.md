# Adding sources

A source is a directory OneSearch is allowed to scan. Most installs have a few: documents, notes, photos, maybe a NAS mount.

## The path is the container path

In Docker, OneSearch only sees paths mounted into the container. If your compose file has this:

```yaml
volumes:
  - /home/alex/Documents:/data/documents:ro
```

then the source path is:

```text
/data/documents
```

not `/home/alex/Documents`.

The `:ro` part is recommended. OneSearch only needs to read your files.

## Add a source in the web UI

Go to **Admin → Sources**, click **Add Source**, then fill in:

- **Name**: something you recognize later, like `Documents` or `NAS Photos`
- **Path**: the container path, such as `/data/documents`
- **Include patterns**: optional comma-separated globs
- **Exclude patterns**: optional comma-separated globs
- **Schedule**: manual, hourly, daily, weekly, custom interval, advanced cron, or "use global default" to follow the schedule configured under Settings

Use **Test** next to Root Path before saving. It checks whether the path is inside allowed roots, exists, is a directory, and is readable by OneSearch from inside the container. If you accidentally enter a host path, the test can point you back toward the mounted container path.

After saving, run a reindex from the same page unless you set a schedule and are happy to wait for the next run.

## Add a remote source

Remote agents are optional. Local remains the default and uses a path mounted read-only on the server. To use a remote machine instead, enable **Remote agents** in Settings, enroll and approve its agent, and wait for it to show `online` under **Admin > Agents**.

In the source form:

1. Choose **Remote agent** as the location.
2. Select the approved agent.
3. Select an advertised allowed root or enter a path beneath one. The path uses the agent machine's syntax.
4. Choose **Test path** and wait for the completed result. The test checks that the path is inside an allowed root, exists, is a directory, and is readable by the agent process.
5. Choose a processing mode. **Inherit agent default** follows the default shown on the Agents page. **On agent** extracts files on the remote machine. **On server** transfers changed files to temporary server storage for extraction.
6. Choose the schedule in the same way as a local source.

The source belongs to the OneSearch server, not the agent. An agent is a connection to a machine and does not automatically create sources for everything below its allowed roots.

Remote sources use the central scheduler. **Use global default** follows the schedule configured in Settings. Otherwise, the source can use its own interval, cron schedule, or manual-only setting. Agents have no schedule of their own. If the agent is offline when a scan is due, OneSearch keeps one pending catch-up scan for that source instead of queueing every missed occurrence. Agent details show the job reason as `catch_up`.

Search, indexed document details, and stored image previews remain available from the server while the agent is offline. Downloading an original remote file, or generating a preview that was not stored during indexing, requires the agent to reconnect.

See [Remote agents](../administration/remote-agents.md) for enrollment, service, privacy, updates, and removal.

## Add a source with the CLI

```bash
onesearch source add "Documents" /data/documents
```

With patterns:

```bash
onesearch source add "Notes" /data/notes \
  --include "**/*.md,**/*.txt" \
  --exclude "**/.git/**,**/node_modules/**"
```

If the path exists only inside Docker, your local CLI machine may not be able to validate it. Use:

```bash
onesearch source add "Documents" /data/documents --no-validate
```

## Add a source with the API

```bash
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Documents",
    "root_path": "/data/documents",
    "include_patterns": ["**/*.pdf", "**/*.md", "**/*.txt"],
    "exclude_patterns": ["**/.git/**", "**/node_modules/**"],
    "scan_schedule": "@daily"
  }'
```

`include_patterns` and `exclude_patterns` are arrays in the API. The CLI and web UI accept comma-separated text and convert it for you.

## Pattern examples

| Pattern | What it does |
|---------|--------------|
| `**/*.pdf` | all PDFs below the source root |
| `**/*.md, **/*.txt` | Markdown and text files when entered in the web UI or CLI |
| `docs/**/*` | everything under a `docs` folder |
| `**/.git/**` | skip Git internals |
| `**/node_modules/**` | skip Node dependencies |
| `**/__pycache__/**` | skip Python cache directories |
| `**/.st*/**` | skip Syncthing folders such as `.stfolder`, `.stignore`, and `.stversions` |

Directory excludes such as `**/node_modules/**` apply to all descendants of matching folders, not just direct children. The web UI and CLI split pattern text on commas, so prefer separate comma-separated patterns over brace groups that contain commas.

If you leave includes empty, OneSearch scans everything it supports. Default excludes already skip common dependency/build folders when no custom excludes are provided.

## Changing a source

Editing the path or patterns affects future indexing. If you want old indexed documents cleaned up immediately, run a reindex after saving. Use a full reindex if the old settings indexed a lot of things you no longer want.
