# OneSearch CLI

Command-line interface for OneSearch - Self-hosted, privacy-focused search for your homelab.

## Installation

### From Source (Development)

```bash
cd cli
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -e .
```

### Verify Installation

```bash
onesearch --version
onesearch --help
```

## Quick Start

```bash
# Check system health
onesearch health

# List configured sources
onesearch source list

# Add a source
onesearch source add "Documents" /data/docs --include "**/*.pdf,**/*.md"

# Trigger indexing
onesearch source reindex 1

# Search
onesearch search "kubernetes deployment"

# Check indexing status
onesearch status
```

## Commands

### Source Management

```bash
# List all sources
onesearch source list

# Add a new source
onesearch source add <name> <path> [--include PATTERNS] [--exclude PATTERNS]

# Show source details
onesearch source show <source_id>

# Reindex a source
onesearch source reindex <source_id>

# Delete a source
onesearch source delete <source_id> [--yes]
```

### Search

```bash
# Basic search
onesearch search "query"

# With filters
onesearch search "python" --source 1 --type pdf --limit 10

# JSON output for scripting
onesearch search "error" --json | jq '.results[].path'

# Pagination
onesearch search "docker" --offset 20 --limit 10
```

### Status & Health

```bash
# Overall status
onesearch status

# Specific source status
onesearch status <source_id>

# System health check
onesearch health

# JSON output for monitoring
onesearch health --json
```

## Configuration

### Environment Variables

- `ONESEARCH_URL` - Backend API URL (default: `http://localhost:8000`)

```bash
# Use a custom backend URL
export ONESEARCH_URL=http://onesearch.local:8000
onesearch search "test"

# Or pass directly
onesearch --url http://onesearch.local:8000 search "test"
```

### Global Options

- `--url URL` - Override backend API URL
- `-v, --verbose` - Enable verbose output
- `-h, --help` - Show help message
- `--version` - Show version

## Output Formats

Most commands support `--json` for machine-readable output:

```bash
# JSON for scripting
onesearch health --json
onesearch status --json
onesearch search "test" --json
```

## Examples

### Add and Index a Source

```bash
# Add a documents source
onesearch source add "My Documents" /mnt/nas/documents \
  --include "**/*.pdf,**/*.md,**/*.txt" \
  --exclude "**/archive/**"

# Start indexing
onesearch source reindex 1

# Monitor progress
onesearch status 1
```

### Search with Filters

```bash
# Search PDFs only
onesearch search "quarterly report" --type pdf

# Search specific source
onesearch search "meeting notes" --source 1

# Get more results
onesearch search "python" --limit 50
```

### Health Monitoring

```bash
# Quick health check (returns non-zero on failure)
onesearch health || echo "OneSearch is down!"

# JSON for monitoring systems
onesearch health --json | jq '.status'
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```
