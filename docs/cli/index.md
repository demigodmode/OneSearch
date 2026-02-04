# CLI Overview

The OneSearch command-line interface lets you manage sources, search documents, and automate workflows from the terminal.

## Why Use the CLI

**Automation**: Script indexing and searches in cron jobs or CI/CD pipelines.

**Remote management**: Control OneSearch from any machine that can reach the API.

**JSON output**: Parse results programmatically with `--json`.

**Speed**: Faster than clicking through the web UI once you know the commands.

---

## Installation

Install using pip:

```bash
cd cli
pip install -e .
```

Once published to PyPI, you'll be able to install with:

```bash
pip install onesearch-cli
```

See the [CLI Installation Guide](installation.md) for details.

---

## Quick Start

Configure the API endpoint:

```bash
# Initialize config file
onesearch config init

# Set URL if not localhost
onesearch config set url http://192.168.1.100:8000

# Or use environment variable
export ONESEARCH_URL=http://192.168.1.100:8000
```

Basic commands:

```bash
# Check connection
onesearch health

# Add a source
onesearch source add "Documents" /data/docs --include "**/*.pdf,**/*.md"

# List sources
onesearch source list

# Trigger indexing
onesearch source reindex documents

# Search
onesearch search "kubernetes deployment"

# Check status
onesearch status
```

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
onesearch config get url

# Set value
onesearch config set url http://localhost:8000

# Initialize config file
onesearch config init
```

---

## Global Options

These work with any command:

```bash
--quiet, -q          # Minimal output
--json               # JSON format
--url URL            # Override API URL
--help               # Show help
```

Examples:

```bash
# Quiet mode
onesearch search "docker" --quiet

# JSON for scripting
onesearch source list --json | jq '.[] | .name'

# Custom URL
onesearch --url http://nas.local:8000 status
```

---

## Output Formats

### Table (Default)

```
┌──────────┬────────────┬───────────┬──────────┐
│ ID       │ Name       │ Path      │ Files    │
├──────────┼────────────┼───────────┼──────────┤
│ docs     │ Documents  │ /data/docs│ 1,234    │
└──────────┴────────────┴───────────┴──────────┘
```

### JSON

```json
[
  {
    "id": "docs",
    "name": "Documents",
    "root_path": "/data/docs",
    "total_files": 1234
  }
]
```

---

## Configuration

The CLI stores config in a platform-specific location:

- **Linux/macOS**: `~/.config/onesearch/config.json`
- **Windows**: `%APPDATA%\onesearch\config.json`

Example config:

```json
{
  "url": "http://localhost:8000",
  "timeout": 30
}
```

You can override with the `ONESEARCH_URL` environment variable.

See the [Configuration Guide](configuration.md) for details.

---

## Scripting Examples

### Automated Reindexing

```bash
#!/bin/bash
# Reindex all sources nightly

for source in $(onesearch source list --json | jq -r '.[].id'); do
  echo "Reindexing $source..."
  onesearch source reindex "$source"
done
```

### Search and Process

```bash
#!/bin/bash
# Find PDFs mentioning "invoice" and copy them

onesearch search "invoice" --type pdf --json | \
  jq -r '.[].path' | \
  xargs -I {} cp {} /backup/invoices/
```

### Health Monitoring

```bash
#!/bin/bash
# Alert if OneSearch is down

if ! onesearch health --quiet; then
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
