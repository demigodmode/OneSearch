# Troubleshooting

## Remote agents

Start with the state shown under **Admin > Agents**:

- `pending`: enrollment saved a credential, but an administrator has not approved the agent. Approve it before expecting jobs to run.
- `offline`: the approved agent has not contacted the server recently. Check the service or container, DNS, TLS, firewall rules, and the configured server URL.
- `disabled`: enable the agent from its details before restarting it.
- `revoked`: the credential cannot be restored. Remove the local credential or state volume and enroll again with a new code.

An agent marked `online` has made a recent heartbeat, but an individual job can still fail. Open its details to inspect recent job states and attached sources.

### Check the configuration

Use the same absolute configuration path used during enrollment and service installation:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml config check
```

This also validates that every allowed root exists, is an absolute directory, and is readable by the current process. The `--server` value passed to `enroll` must match `server_url` in the file.

For Docker:

```bash
docker compose run --rm onesearch-agent config check
docker compose ps onesearch-agent
docker compose logs -f onesearch-agent
```

The config path and source paths are container paths. Confirm that the config mount is read-only, the state volume is writable, and each source mount is read-only but readable by `PUID` and `PGID`.

### Check the native service

Linux uses a per-user systemd service:

```bash
systemctl --user status onesearch-agent.service
journalctl --user -u onesearch-agent.service -f
```

Run those commands as the user that installed the service. If it stops after logout, configure systemd user lingering for that account.

On Windows, open an elevated PowerShell window:

```powershell
Get-Service OneSearchAgent
& 'C:\Program Files\OneSearch Agent\onesearch-agent.exe' --config 'C:\ProgramData\OneSearch Agent\config.toml' config check
```

The Windows service requires its protected machine credential. Re-run `service install` from the same enrolled user only after confirming the user credential is still available.

### Path rejected or still pending

A remote source path must be at or below an allowed root advertised by the selected agent. Use the path syntax of the agent operating system, not the server. Paths with `..`, Windows paths sent to a Linux agent, Linux paths sent to a Windows agent, and paths outside allowed roots are rejected.

The agent must be online to test a remote path. Start the test and wait for the completed result before saving the source. If it remains pending, inspect the agent's job list and connection. A successful test confirms that the path exists, is a directory, is readable by the agent process, and remains inside an allowed root.

### Protocol version incompatible

An incompatible agent stops polling instead of attempting work with a mismatched wire format. Check the server release notes and install an agent release whose supported protocol range overlaps the server. Update both sides if the release notes require it.

### Update check fails

Manual and automatic checks require outbound HTTPS access to the OneSearch GitHub release host. Check DNS, proxy, firewall, and TLS trust on the agent machine. OneSearch rejects an invalid signature, mismatched platform, incompatible protocol range, malformed version, or artifact whose size or SHA-256 digest does not match its signed manifest.

Docker never self-updates. Change its pinned image tag, pull, and recreate the container. Native auto-update requires the packaged agent and updater files next to each other and an installed operating-system service.

### Preview or download unavailable

Indexed content stays searchable while an agent is offline, but the server needs an online agent to retrieve an original remote file. Reconnect the agent and retry. A `remote_file_missing` error means the path no longer exists. A `remote_file_changed` error means its size or modification time changed after indexing; reindex the source before retrying. RAW embedded previews are not supported for remote files.

If a machine or credential is lost, revoke the agent before enrolling a replacement.

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

Use **Test** next to the Root Path field in **Admin → Sources** first. It reports whether the path is inside allowed roots, exists, is a directory, and is readable from inside the container.

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

Use **Clean** on the status page for that source. It removes missing failed files and retries files that still exist. Files that still cannot be indexed stay visible with their latest error.

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
