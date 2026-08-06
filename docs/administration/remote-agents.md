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

The agent has no separate schedule. If a due scan cannot run while the agent is offline, OneSearch retains one pending scan for that source. Repeated due times do not create a backlog. The pending scan runs after the agent reconnects.

## Processing modes

Processing mode controls where OneSearch reads file contents. It does not change who owns the source or original files.

### On agent

The agent reads and extracts each file locally. It sends normalized text, metadata, and reconciliation data to the server. This reduces original-file transfer, but extraction uses CPU and memory on the agent machine.

### On server

The agent scans metadata first. For changed files, it streams bounded file data to the server for extraction. The server uses temporary storage while processing and does not retain the original file after extraction. This moves extraction work to the server at the cost of more network traffic.

In both modes, the server stores indexed text and metadata in its search index and database. Original files stay on the agent machine. Search results and indexed document details remain available while an agent is offline. A preview or original download that needs the source file requires the agent to be online. Remote RAW embedded previews are not available.

## Health and access states

The Agents page shows last contact, attached sources, indexed document count, recent jobs, pending work, and next scheduled activity.

| State | Meaning |
| --- | --- |
| `pending` | Enrollment succeeded, but an administrator has not approved the agent. |
| `online` | The approved agent has contacted the server recently. |
| `offline` | The agent is approved, but its heartbeat is stale or it has not connected since approval. |
| `disabled` | The server rejects the credential until an administrator enables the agent again. Sources and indexed data remain attached. |
| `revoked` | The server has permanently invalidated the agent token. Re-enrollment with a new code is required. |

Disable an agent for a reversible stop. Revoke it if the credential or machine is lost, compromised, or retired. Revocation cannot be undone.

## Updates

Update checks are off by default. Run a manual signed-manifest check with:

```bash
onesearch-agent --config /etc/onesearch-agent/config.toml update check
```

This contacts the OneSearch GitHub release host. It does not install anything.

Set `auto_update = true` only if the agent may make that outbound request at startup. A native auto-update also requires the packaged agent and updater to remain side by side and the agent to run through its installed operating-system service. The updater verifies the signed manifest, artifact size, and SHA-256 digest before replacing the stopped agent. It restores the last working binary if the new service does not become healthy.

Docker agents check for a compatible release when `auto_update = true`, but never replace their own image. Pin the image tag and update it through your normal container deployment process.

For a manual native update, download the matching agent and updater pair from the same release. Follow the release checksum instructions, uninstall the service, replace both files, and install the service again with the same absolute configuration path. Agent and server protocol ranges must overlap. An incompatible agent stops instead of continuing to claim work.

## Backup, restore, and removal

Remote-source records and indexed data live in the OneSearch database and search index. Include both in server backups as described in [Backup and restore](backup-restore.md).

Agent state contains credentials and update recovery files. Treat a Docker state-volume backup as a secret. Native credentials may live in the operating-system credential store and should not be copied casually to another machine. Re-enrollment is safer than cloning an agent identity. Back up the non-secret configuration separately, then verify allowed-root permissions after restore.

To retire an agent cleanly:

1. Delete or move its remote sources in OneSearch. This removes their indexed data but never deletes originals.
2. Revoke the agent in **Admin > Agents**.
3. Uninstall the native service or stop and remove the container.
4. Remove the local state and configuration only after confirming that the credential was revoked.

If the machine is unavailable, revoke its credential first, then remove its sources.
