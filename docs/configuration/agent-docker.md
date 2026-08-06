# Docker agent

The Docker agent makes outbound HTTP or HTTPS connections to OneSearch and exposes no inbound port. It uses a persistent state volume for its credential and runtime state. Mount its configuration separately as read-only, and mount every allowed source root read-only.

Agent images are built for Linux amd64 and Linux arm64 by the agent release workflow. Use a version tag from the matching OneSearch release when an image has been published. Do not use `latest` for an unattended installation.

## Configuration

Create `agent.toml` before enrollment:

```toml
server_url = "https://search.example"
agent_name = "storage-node"
state_dir = "/var/lib/onesearch-agent"
credential_store = "file"
auto_update = false

[[allowed_roots]]
root_id = "documents"
path = "/sources/documents"
display_name = "Documents"
read_only = true
```

The paths in this file are container paths. The state directory must remain `/var/lib/onesearch-agent` for the volume layout below.

Create a compose override or separate compose file:

```yaml
services:
  onesearch-agent:
    image: ghcr.io/demigodmode/onesearch-agent:<VERSION>
    restart: unless-stopped
    environment:
      PUID: "1000"
      PGID: "1000"
      ONESEARCH_AGENT_CONFIG: /etc/onesearch-agent/agent.toml
    volumes:
      - ./agent.toml:/etc/onesearch-agent/agent.toml:ro
      - onesearch_agent_state:/var/lib/onesearch-agent
      - /srv/documents:/sources/documents:ro

volumes:
  onesearch_agent_state:
```

Replace `<VERSION>` with a published version that matches your server release. Set `PUID` and `PGID` to a non-root host user and group that can read the mounted source directories. The entrypoint changes ownership of the state volume to that identity. It rejects UID or GID 0.

Check the configuration:

```bash
docker compose run --rm onesearch-agent config check
```

## Enroll once

Enable remote agents in the OneSearch settings, create an enrollment code in **Admin > Agents**, then run:

```bash
docker compose run --rm onesearch-agent enroll --server https://search.example
```

Enter the code at the hidden prompt. Compose uses the same persistent state volume for this one-shot command and the long-running service, so the saved agent credential remains available. Do not put the code or agent token in compose YAML, environment variables, or command arguments.

Approve the pending machine in **Admin > Agents**, then start it:

```bash
docker compose up -d onesearch-agent
docker compose logs -f onesearch-agent
```

The agent runs the image's default `run` command. Do not add an enrollment command to the service definition.

## Updates

With `auto_update = false`, the container makes no release-host update request. You can run a manual signed-manifest check:

```bash
docker compose run --rm onesearch-agent update check
```

With `auto_update = true`, the container checks the OneSearch GitHub release host when it starts and reports a compatible update. It does not download a replacement binary or replace its image.

To update, change the pinned image tag, pull it, and recreate the service:

```bash
docker compose pull onesearch-agent
docker compose up -d onesearch-agent
```

Keep the state volume and configuration mount in place. Review the release notes for agent and server protocol compatibility before changing only one side.

## Remove the container

Delete or move the agent's sources in OneSearch, then revoke its credential from **Admin > Agents**. Stop the container after revocation:

```bash
docker compose down
```

The named state volume contains the agent credential. Remove it only after revocation and only when you do not need to restore this agent identity.
