# Remote agents

Remote agents let OneSearch index files on another machine without mounting those files on the OneSearch server. They are optional and disabled by default. Local sources remain the default, and read-only NFS, SMB, bind, and ZFS mounts continue to work without an agent.

An agent represents a machine connection. It does not turn the whole machine into a source. The agent advertises a small set of allowed roots from its local configuration, and an administrator creates each source on the OneSearch server at or below one of those roots.

## Before you enroll

1. Enable **Remote agents** under **Admin > Settings**.
2. Download the native agent and updater assets for your platform from a OneSearch release when those assets are included:

   - Linux amd64
   - Linux arm64
   - Windows x64

   OneSearch does not provide an apt repository or system package for the agent.
3. Put the agent and updater next to each other in a directory that will not move after service installation. Rename the downloaded files to `onesearch-agent` and `onesearch-agent-updater` on Linux, or `onesearch-agent.exe` and `onesearch-agent-updater.exe` on Windows. On Linux, make both files executable.
4. Create the allowed directories and a non-secret configuration file. Use absolute paths for the configuration file, state directory, and allowed roots.

Example Linux configuration at `/etc/onesearch-agent/config.toml`:

```toml
server_url = "https://search.example"
agent_name = "archive-node"
state_dir = "/var/lib/onesearch-agent"
credential_store = "auto"
auto_update = false

[[allowed_roots]]
root_id = "documents"
path = "/srv/documents"
display_name = "Documents"
read_only = true
```

The agent process must be able to read each allowed root and write to `state_dir`. `credential_store = "auto"` uses a secure system credential store when one is available and otherwise uses a permission-restricted file on Linux. Native Windows agents require the Windows credential store.

Check the file before enrollment:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml config check
```

For Windows, use an absolute Windows path in an elevated PowerShell window:

```toml
server_url = "https://search.example"
agent_name = "archive-node"
state_dir = "C:\\ProgramData\\OneSearch Agent\\state"
credential_store = "auto"
auto_update = false

[[allowed_roots]]
root_id = "documents"
path = "D:\\Documents"
display_name = "Documents"
read_only = true
```

Create the state and allowed-root directories before checking the configuration.

```powershell
& 'C:\Program Files\OneSearch Agent\onesearch-agent.exe' --config 'C:\ProgramData\OneSearch Agent\config.toml' config check
```

## Enroll and approve

In **Admin > Agents**, choose **Add agent enrollment**. The code is valid for 15 minutes and can be used once.

Run enrollment on the machine that will run the agent:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml enroll --server https://search.example
```

The command prompts for the enrollment code without echoing it. Do not put the code in an argument, compose file, or shell history. The `--server` value must match `server_url` in the configuration.

The server returns an agent token during enrollment, and the agent saves it locally. The machine then appears with **Pending approval** status. It cannot claim work until an administrator approves it in **Admin > Agents**.

The enrollment code, agent token, and user login token are separate credentials:

- The enrollment code creates one pending agent record and then expires.
- The agent token authenticates only the agent protocol. It cannot sign in to the web interface.
- A user login token authenticates administrative and search API requests. It cannot authenticate an agent.

## Run as a service

The configuration path used for service installation must be absolute. Enrollment must already have saved a credential that the service can access.

### Linux

Install and start the per-user systemd service as the same user that enrolled the agent:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml service install
systemctl --user status onesearch-agent.service
journalctl --user -u onesearch-agent.service -f
```

This is a user service, not a system service. Configure systemd user lingering if the agent must run while that user is logged out. Remove the service with:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml service uninstall
```

### Windows

Run service installation from an elevated PowerShell window. Windows installs `OneSearchAgent` as an automatically started service and protects a machine-level copy of the enrolled credential for the service account.

```powershell
& 'C:\Program Files\OneSearch Agent\onesearch-agent.exe' --config 'C:\ProgramData\OneSearch Agent\config.toml' service install
Get-Service OneSearchAgent
```

Remove it from an elevated PowerShell window:

```powershell
& 'C:\Program Files\OneSearch Agent\onesearch-agent.exe' --config 'C:\ProgramData\OneSearch Agent\config.toml' service uninstall
```

For Docker setup, see [Docker agent](../configuration/agent-docker.md).

## Create remote sources

The server owns source configuration and scheduling. After the agent is online, create a source under **Admin > Sources**:

1. Select **Remote agent** as the location.
2. Select an approved agent.
3. Choose a path at or below one of its allowed roots, run the path test, and wait for its completed result.
4. Choose a processing mode or inherit the agent default.
5. Use the global schedule, set a schedule for this source, or leave it manual.

The agent has no separate schedule. If a due scan cannot run while the agent is offline, OneSearch retains one pending scan for that source. Repeated due times do not create a backlog. The job is recorded with the `catch_up` reason and runs after the agent reconnects. An ordinary scheduled job that was already pending keeps its original `schedule` reason.

## Processing modes

Processing mode controls where OneSearch reads file contents. It does not change who owns the source or original files.

### On agent

The agent reads and extracts each file locally. It sends normalized text, metadata, and reconciliation data to the server. This reduces original-file transfer, but extraction uses CPU and memory on the agent machine. The extractors ship with the agent, so update the agent binary or image to get extraction changes.

### On server

The agent scans metadata first. For changed files, it streams bounded file data to the server for extraction. The server uses temporary storage while processing and does not retain the original file after extraction. This moves extraction work to the server at the cost of more network traffic. The extractors run on the server and receive extraction changes when you update the server.

In both modes, the server stores indexed text and metadata in its search index and database. Original files stay on the agent machine. Search results, indexed document details, and stored image previews remain available while an agent is offline. An original download, or a preview that was not stored during indexing, requires the agent to be online. Remote RAW embedded previews are not available.

## Health and access states

The Agents page shows last contact, attached sources, indexed document count, recent jobs, pending work, and next scheduled activity.

| State | Meaning |
| --- | --- |
| `pending` | Enrollment succeeded, but an administrator has not approved the agent. |
| `online` | The approved agent has contacted the server recently. |
| `degraded` | The agent is connected, but one or more sources had an indexing failure in the last 24 hours. It can still run jobs and test paths. |
| `offline` | The agent is approved, but its heartbeat is stale or it has not connected since approval. |
| `disabled` | The server rejects the credential until an administrator enables the agent again. Sources and indexed data remain attached. |
| `revoked` | The server has permanently invalidated the agent token. Re-enrollment with a new code is required. |

Disable an agent for a reversible stop. Revoke it if the credential or machine is lost, compromised, or retired. Revocation cannot be undone.

The Sources page and search results show **Agent offline**, **Agent disabled**, or **Agent revoked** beside affected sources and results. Their indexed content and stored previews remain available unless you delete the sources. Original downloads require an available agent; reconnect an offline agent or enable a disabled one. A revoked credential cannot reconnect.

Turning off **Remote agents** in Settings also marks remote sources and results as **Agent disabled**; revoked agents still read **Agent revoked**. A degraded agent remains connected and can serve originals, so its sources do not get an unavailable badge.

Degraded health is based on each source's most recent completed or failed scan. A failed scan marks the source as affected. A completed scan also counts when the source still has failed file records. A later successful scan with no remaining file failures clears the warning. The warning also expires when the source has no qualifying scan in the last 24 hours. Offline, disabled, and revoked states take priority over degraded health.

## Updates

The Agents page reports update availability; there is no self-update button in the UI. A native agent is installed directly on Linux or Windows. It can install updates automatically when it runs as a service with `auto_update = true` and the packaged updater. Otherwise, update the native files manually. A Docker agent runs in a container; pull its new image and recreate the container to update it.

`auto_update` controls installation, not availability checks. At startup and about every 24 hours, agents check the signed OneSearch GitHub release manifest for a compatible update. A failed availability check retries about hourly and is reported to the administrator; it never stops indexing. Run a manual signed-manifest check with:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml update check
```

This contacts the OneSearch GitHub release host for signed release metadata and does not install anything. It does not include indexed content, source paths, search queries, or the agent credential. Set `auto_update = true` only to allow a native agent to install an available signed update. Native installation also requires the packaged agent and updater to remain side by side and the agent to run through its installed operating-system service. The updater verifies the signed manifest, artifact size, and SHA-256 digest before replacing the stopped agent. It restores the last working binary if the new service does not become healthy.

Docker agents are always notify-only: they check for availability but never download an artifact or replace their own image. Pin the image tag and update it through your normal container deployment process.

If the page says **Update checks aren't configured for this build**, the agent has no embedded release signing key. This is expected for a local or development build without that key and does not stop indexing. Official release builds include the key used to verify update manifests.

For a manual native update, download the matching agent and updater pair from the same release. Follow the release checksum instructions, uninstall the service, replace both files, and install the service again with the same absolute configuration path. Agent and server protocol ranges must overlap. An incompatible agent stops instead of continuing to claim work.

## Backup, restore, and removal

Remote-source records and indexed data live in the OneSearch database and search index. Derived remote image previews live in the server data directory: beside the SQLite database by default, or under `/app/data/previews` when the database is elsewhere. Include the database, search index, and preview directory in server backups as described in [Backup and restore](backup-restore.md). Previews can be regenerated by reindexing while the agent is online, but offline previews remain unavailable until regeneration finishes.

Agent state contains credentials and update recovery files. Treat a Docker state-volume backup as a secret. Native credentials may live in the operating-system credential store and should not be copied casually to another machine. Re-enrollment is safer than cloning an agent identity. Back up the non-secret configuration separately, then verify allowed-root permissions after restore.

To retire an agent:

1. Open its details in **Admin > Agents** and choose **Revoke credential**.
2. Leave **Also delete this agent's sources** unchecked to keep their indexed content and stored previews, or select it to remove the sources and indexed documents. Choose **Confirm revoke**.
3. Uninstall the native service or stop and remove the container.
4. Remove the local state and configuration only after confirming that the credential was revoked.

Source deletion also cleans up stored previews; failures to remove preview files are logged on the server. Original files on the agent machine are never deleted. Revocation and source deletion cannot be undone in the UI. Back up data you need before deleting sources.

The credential is revoked before source cleanup starts. If cleanup fails, the agent stays revoked and some sources may already be deleted. A revoked agent with sources shows **Delete remaining sources** in its details. Use it to retry cleanup or to remove sources you chose to keep when revoking. The remote machine does not need to be online for this cleanup.
