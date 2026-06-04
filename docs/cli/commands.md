# Command Reference

The CLI is a thin client for a running OneSearch server. Most commands need a configured backend URL and a login token.

Global options work before any command:

```bash
onesearch --url http://localhost:8000 status
onesearch --quiet search "invoice"
onesearch --verbose health
```

`--url` can also come from `ONESEARCH_URL` or `onesearch config set backend_url ...`.

## Auth

### `onesearch login`

Prompts for username and password, then stores the returned token in the CLI config.

```bash
onesearch login
```

For scripts or pre-issued tokens:

```bash
onesearch login --token
```

### `onesearch logout`

Removes the stored token.

```bash
onesearch logout
```

### `onesearch whoami`

Checks which user the stored token belongs to.

```bash
onesearch whoami
```

## Sources

### `onesearch source list`

Shows configured sources.

```bash
onesearch source list
```

### `onesearch source add <name> <path>`

Adds a directory as a source. In Docker installs, use the container path, not the host path.

```bash
onesearch source add "Documents" /data/documents
onesearch source add "Notes" /data/notes --include "**/*.md,**/*.txt"
onesearch source add "Code" /data/code --exclude "**/node_modules/**,**/.git/**"
```

Options:

- `--include`, `-i`: comma-separated glob patterns to include
- `--exclude`, `-e`: comma-separated glob patterns to skip
- `--no-validate`: skip local path checks, useful when the path exists only inside the container

### `onesearch source show <source_id>`

Prints details for one source.

```bash
onesearch source show documents
```

### `onesearch source delete <source_id>`

Deletes the source config and removes that source's indexed documents from search.

```bash
onesearch source delete documents
onesearch source delete documents --yes
```

### `onesearch source reindex <source_id>`

Runs an incremental reindex. Only new, changed, and deleted files are processed.

```bash
onesearch source reindex documents
```

Use `--full` to clear indexed metadata and rebuild the source from scratch:

```bash
onesearch source reindex documents --full
```

## Search

### `onesearch search <query>`

Searches indexed documents.

```bash
onesearch search "kubernetes deployment"
onesearch search "invoice" --source documents
onesearch search "readme" --type markdown --limit 10
onesearch search "error" --json
```

Options:

- `--source`, `-s`: filter by source ID
- `--type`, `-t`: filter by `text`, `markdown`, or `pdf`
- `--limit`, `-l`: max results, default 20
- `--offset`, `-o`: pagination offset
- `--json`: print raw JSON for scripts

## Status and health

### `onesearch status`

Shows indexing status for all sources.

```bash
onesearch status
onesearch status --json
```

For one source:

```bash
onesearch status documents
```

### `onesearch health`

Checks backend and Meilisearch health.

```bash
onesearch health
onesearch health --json
```

## Config

### `onesearch config show`

Prints the current CLI config.

```bash
onesearch config show
onesearch config show --path
```

### `onesearch config get <key>`

```bash
onesearch config get backend_url
```

### `onesearch config set <key> <value>`

```bash
onesearch config set backend_url http://localhost:8000
onesearch config set defaults.search_limit 50
```

Values are parsed as YAML, so `false`, `50`, and nested values keep their types.

### `onesearch config unset <key>`

```bash
onesearch config unset auth.token
```

### `onesearch config init`

Creates a default config file.

```bash
onesearch config init
onesearch config init --force
```

### `onesearch config path`

Prints the config path.

```bash
onesearch config path
```

## Built-in help

The CLI help is the source of truth for flags on your installed version:

```bash
onesearch --help
onesearch source --help
onesearch source reindex --help
onesearch search --help
```
