# OneSearch

Self-hosted, privacy-focused search for your homelab.

Search across all your files, documents, and notes from a single interface. No cloud dependencies, no telemetry, just fast local search powered by Meilisearch.

---

## Features

**Fast full-text search** with typo tolerance and relevance ranking. OneSearch uses Meilisearch under the hood, so searches are typically sub-second even with millions of documents.

**Multiple file types supported**: text files, markdown, PDFs, and Microsoft Office documents (Word, Excel, PowerPoint).

**Multiple sources**: Index local directories, NAS shares, or external drives. Each source can have its own include/exclude patterns.

**Incremental indexing**: Only changed files get reindexed, so updates are fast. Full reindex available when you need it.

**Scheduled indexing**: Set per-source cron schedules (hourly, daily, weekly, or custom) so sources stay up to date automatically.

**Authentication**: JWT-based login with a setup wizard. Rate-limited to prevent brute force.

**Three ways to use it**: Web UI for browsing and searching, REST API for integrations, and CLI for automation.

**Privacy first**: Everything runs locally. No outbound connections, no telemetry, no cloud services. Your data never leaves your network.

---

## Quick Start

Get OneSearch running in a few minutes:

```bash
# Create project directory
mkdir onesearch && cd onesearch

# Download docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml

# Download and configure environment
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env
# Edit .env and set MEILI_MASTER_KEY (generate with: openssl rand -base64 32)

# Start it up
docker-compose up -d
```

Open http://localhost:8000, create your admin account in the setup wizard, and you're ready to go.

For detailed setup instructions, see the [Installation Guide](getting-started/installation.md).

---

## What's New

v0.7.2 is the current stable release with Phase 1 complete — authentication, scheduled indexing, Office document support, and comprehensive security hardening. This release enforces JWT auth on all API endpoints, adds CORS configuration, improves performance with SQL optimizations, and fixes a bunch of deployment bugs found during real-world testing.

Check the [Changelog](about/changelog.md) for details.

---

## How to Use It

### Web Interface

The main search page gives you a Google-like search box with filters for source and file type. Click any result to see the full document with syntax highlighting. The admin section lets you manage sources and monitor indexing status.

[Web UI Guide](user-guide/web-interface.md)

### Command Line

The CLI is great for automation and scripting. Add sources, trigger reindexing, and search from the command line. Supports JSON output for easy parsing.

[CLI Documentation](cli/index.md)

### REST API

Full API access for custom integrations. All the web UI functionality is available via API endpoints.

[API Reference](api/index.md)

---

## Common Use Cases

**Personal knowledge base**: Search across notes, documents, and downloads from one place.

**Homelab documentation**: Index config files, logs, and technical docs scattered across your servers.

**Research library**: Full-text search across PDFs, academic papers, and research notes.

**Media libraries**: Search file names and metadata across large collections (EXIF support coming in Phase 2).

---

## Architecture

OneSearch is built on modern, proven technologies:

- FastAPI (Python) for the backend API
- Meilisearch for fast full-text search
- SQLite for metadata and configuration
- React + TypeScript for the web UI
- Docker Compose for easy deployment

The backend handles indexing and search requests. Meilisearch stores the search index. SQLite tracks which files have been indexed and their metadata. The frontend is served by nginx and talks to the backend API.

See the [Architecture Guide](development/architecture.md) for details.

---

## Support

- [GitHub Issues](https://github.com/demigodmode/OneSearch/issues) for bugs and feature requests
- [Source Code](https://github.com/demigodmode/OneSearch) on GitHub
- Licensed under [AGPL-3.0](about/license.md)

---

## Next Steps

New to OneSearch? Start with the [Installation Guide](getting-started/installation.md).

Already installed? Check out the [User Guide](user-guide/index.md) to learn about adding sources and searching.

Want to automate? See the [CLI Documentation](cli/index.md).

Building integrations? Explore the [API Reference](api/index.md).
