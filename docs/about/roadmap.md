# Roadmap

OneSearch has reached the first stable Docker shape: a single app container with managed Meilisearch by default, plus the legacy external-Meilisearch compose file for people who still want that setup.

The next work is less about proving the idea and more about making big libraries easier to live with.

## Shipped

Recent milestones that are already in the product:

- unified Docker image
- managed Meilisearch as the default install
- legacy external Meilisearch compose support
- setup wizard and JWT auth
- source path restrictions, read-only mount guidance, and source path preflight testing
- scheduled indexing with presets, friendly interval controls, and advanced cron
- full reindex support in the UI, CLI, and API
- Office, PDF, Markdown, text, code, and config indexing
- RTF, EPUB, subtitles, CBZ comics, images, RAW photos, and media metadata
- metadata-only indexing for unsupported files
- document previews, image previews, RAW embedded previews, and format-aware detail views
- Light, Dark, and System theme modes, accent settings, and search display settings
- standalone CLI package
- Podman deployment notes for rootless and SELinux setups

See the [changelog](changelog.md) for release-by-release details.

## Near-term work

These are the kinds of improvements that fit the current product without changing what OneSearch is.

### Search polish

- date, size, and metadata filters
- better type filtering in the CLI
- saved searches or recent searches
- export results as CSV/JSON from the UI
- more useful empty states when filters hide everything

### Indexing and formats

- archive contents beyond CBZ comics, such as `.zip` and `.tar.gz`
- email formats like `.eml` and `.mbox`
- better handling for very large spreadsheets
- clearer failed-file cleanup flows
- more knobs for rich media extraction defaults

### Operations

- cleaner backup/restore workflow
- better status history for scheduled runs
- basic metrics endpoint or Prometheus-friendly output
- easier diagnostics bundle for bug reports

## Larger ideas

These are useful, but they need more design before they should be treated as committed work.

### Connectors

Cloud and remote storage would probably go through rclone or a similar layer:

- Google Drive
- Dropbox
- OneDrive
- S3-compatible storage

### Smarter search

- faceted search
- semantic search with embeddings
- natural-language filters
- document summaries
- auto-tagging

### Access control

Right now, if a user can log in, they can search the indexed content. More granular access would need careful design:

- per-source permissions
- read-only users
- SSO/LDAP/OAuth
- audit logs

## Not planned right now

A few things come up naturally, but they are not immediate priorities:

- mobile apps
- desktop Electron app
- browser extension
- multi-tenant/team workspace features

They may happen later if there is real demand, but the main product still needs the homelab/self-hosted basics to stay solid first.

## Suggesting changes

Open a [GitHub Discussion](https://github.com/demigodmode/OneSearch/discussions) for rough ideas, or a [GitHub Issue](https://github.com/demigodmode/OneSearch/issues) for a specific bug or feature request.

Good requests explain the use case. “Support email archives because I have 20 years of `.mbox` exports I need to search” is much easier to act on than “add email”.
