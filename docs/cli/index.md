# CLI Overview

`onesearch-cli` is a standalone command-line client for a running OneSearch server. It talks to the same backend API as the web UI, so both interfaces share the same sources, indexes, auth, and search results. Tagged OneSearch releases publish the Docker image and the CLI package on the same shared version.

## Why Use the CLI

**Automation**: Script indexing and searches in cron jobs or CI/CD pipelines.

**Remote management**: Control OneSearch from any machine that can reach the API.

**JSON output**: Parse results programmatically with `--json`.

**Fast admin workflow**: Search, inspect status, and manage sources without opening the browser.

---

## Installation

Install the standalone CLI with `pipx`:

```bash
pipx install onesearch-cli
```

You still need a running OneSearch backend somewhere on your network. See the [CLI Installation Guide](installation.md) for details.

---

## Quick Start

Point the CLI at your server, then log in:

```bash
onesearch config set backend_url http://192.168.1.100:8000
onesearch login
onesearch whoami
```

Basic commands:

```bash
onesearch health
onesearch source list
onesearch search "kubernetes deployment"
onesearch status
```

### Docker fallback

If you don't want to install the standalone CLI yet, the Docker image still includes it:

```bash
docker exec -it onesearch-app onesearch status
docker exec -it onesearch-app onesearch whoami
```

That works fine for debugging, but the standalone CLI is the preferred path.

---

## Commands

### Source Management

```bash
# List all sources
onesearch source list

# Add a new source
onesearch source add NAME PATH [OPTIONS]

# Show source details
onesearch source show SOURCE_ID

# Delete a source
onesearch source delete SOURCE_ID

# Trigger reindex (incremental by default)
onesearch source reindex SOURCE_ID

# Full reindex
onesearch source reindex SOURCE_ID --full
```

### Searching

```bash
# Basic search
onesearch search QUERY

# Filter by source
onesearch search QUERY --source documents

# Filter by file type
onesearch search QUERY --type pdf

# Limit results
onesearch search QUERY --limit 20

# JSON output for scripting
onesearch search QUERY --json
```

### Monitoring

```bash
# Overall status
onesearch status

# Source-specific status
onesearch status SOURCE_ID

# Health check
onesearch health
```

### Configuration

```bash
# Show config
onesearch config show

# Get specific value
onesearch config get backend_url

# Set value
onesearch config set backend_url http://localhost:8000

# Show config path
onesearch config path
```

---

## Global Options

These go before the command name:

```bash
--url URL            # Override API URL
--quiet, -q          # Minimal output
--verbose, -v        # More detail
--version            # Print the CLI version
--help, -h           # Show help
```

Examples:

```bash
# Quiet mode
onesearch --quiet search "docker"

# Custom URL
onesearch --url http://nas.local:8000 status
```

`--json` is not global. It belongs to `search`, `status` and `health`, and goes after the command:

```bash
onesearch status --json | jq -r '.sources[].source_name'
```

---

## Output Formats

### Table (Default)

`onesearch source list` prints a table like this:

```
┌──────┬───────────┬────────────┬──────────────────┬──────────────────┐
│ ID   │ Name      │ Root Path  │ Include Patterns │ Exclude Patterns │
├──────┼───────────┼────────────┼──────────────────┼──────────────────┤
│ docs │ Documents │ /data/docs │ **/*.pdf         │ **/drafts/**     │
└──────┴───────────┴────────────┴──────────────────┴──────────────────┘
```

### JSON

`search`, `status` and `health` take `--json` and print the API response as-is. For example `onesearch status --json`:

```json
{
  "sources": [
    {
      "source_id": "docs",
      "source_name": "Documents",
      "total_files": 1234,
      "successful": 1230,
      "failed": 4,
      "skipped": 0
    }
  ]
}
```

The source commands (`source list`, `source add` and so on) only print tables.

---

## Configuration

The CLI stores config in a platform-specific location:

- **Linux/macOS**: `~/.config/onesearch/config.yml`, or `$XDG_CONFIG_HOME/onesearch/config.yml` if that variable is set
- **Windows**: `%APPDATA%\onesearch\config.yml`

Example config:

```yaml
backend_url: http://localhost:8000
auth:
  token: null
```

You can override with `ONESEARCH_URL` and `ONESEARCH_TOKEN`.

See the [Configuration Guide](configuration.md) for details.

---

## Scripting Examples

### Automated Reindexing

```bash
#!/bin/bash
# Reindex all sources nightly

for source in $(onesearch status --json | jq -r '.sources[].source_id'); do
  echo "Reindexing $source..."
  onesearch source reindex "$source"
done
```

### Search and Process

```bash
#!/bin/bash
# Find PDFs mentioning "invoice" and copy them.
# The paths are the server's paths, so run this where those paths exist.

onesearch search "invoice" --type pdf --json | \
  jq -r '.results[].path' | \
  xargs -I {} cp {} /backup/invoices/
```

### Health Monitoring

```bash
#!/bin/bash
# Alert if OneSearch is down

if ! onesearch --quiet health; then
  echo "OneSearch is down!" | mail -s "Alert" admin@example.com
fi
```

See the [Examples & Workflows](examples.md) page for more scripts.

---

## Next Steps

- [Installation Guide](installation.md) - Set up the CLI
- [Configuration](configuration.md) - Configure the CLI
- [Command Reference](commands.md) - Full command docs
- [Examples & Workflows](examples.md) - Real-world scripts

---

## Getting Help

```bash
# General help
onesearch --help

# Command help
onesearch source --help
onesearch search --help
```

Or check the [Troubleshooting Guide](../administration/troubleshooting.md).
