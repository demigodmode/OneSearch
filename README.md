# OneSearch

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

**Self-hosted, privacy-focused search for your homelab**

Search across all your files, documents, and notes from a single, unified interface. No cloud dependencies, no telemetry, just fast local search.

---

## Features (Phase 0 MVP)

- **Fast Full-Text Search** - Powered by Meilisearch with typo tolerance and relevance ranking
- **Multiple File Types** - Text, Markdown, and PDF support
- **Multiple Sources** - Index local directories, mounted NAS shares, or external drives
- **Incremental Indexing** - Only reindex changed files, not your entire library
- **REST API** - Full-featured API for search, source management, and status
- **CLI Tool** - Command-line interface for scripting and automation
- **Web UI** - React-based interface (scaffold in Phase 0, full functionality coming in Phase 1)
- **Privacy First** - All data stays local, no outbound connections
- **Easy Deployment** - Single Docker Compose command to get started

> **Note:** Phase 0 focuses on backend functionality. The Web UI is a scaffold with mock data—use the CLI or API for full functionality until Phase 1 wiring is complete.

---

## Quick Start

This repo ships with a ready-to-use `docker-compose.yml` that starts the backend API, Meilisearch, and the frontend together. The steps below use it.

### Prerequisites

- Docker and Docker Compose installed
- At least 4GB RAM and 2 CPU cores
- Storage for your search index (~10-50% of source data size)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/demigodmode/OneSearch.git
   cd OneSearch
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```

3. **Generate a secure Meilisearch key**
   ```bash
   # On Linux/Mac
   openssl rand -base64 32

   # On Windows (PowerShell)
   -join (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
   ```

   Edit `.env` and set your `MEILI_MASTER_KEY`:
   ```
   MEILI_MASTER_KEY=your-generated-key-here
   ```

4. **Configure source mounts (optional)**

   Edit `docker-compose.yml` and uncomment/add volume mounts under the `onesearch` service:
   ```yaml
   volumes:
     - onesearch_data:/app/data
     # Add your sources here (read-only recommended)
     - /mnt/nas/documents:/data/nas_docs:ro
     - /home/user/Documents:/data/documents:ro
   ```

5. **Start OneSearch**
   ```bash
   docker-compose up -d
   ```

6. **Access the UI**

   Open http://localhost:8000 in your browser

---

## Usage

> **Phase 0:** Use the CLI or API for full functionality. Web UI is a design scaffold.

### Using the CLI (Recommended)

```bash
# Install CLI
cd cli && pip install -e .

# Add a source (use --no-validate for Docker-only paths)
onesearch source add "Documents" /data/docs --include "**/*.pdf,**/*.md" --no-validate

# Trigger indexing
onesearch source reindex documents

# Search
onesearch search "kubernetes deployment"

# Check status
onesearch status
```

See [cli/README.md](cli/README.md) for full CLI documentation.

### Using the API

```bash
# Add a source
curl -X POST http://localhost:8000/api/sources \
  -H "Content-Type: application/json" \
  -d '{"name": "Documents", "root_path": "/data/docs"}'

# Trigger incremental reindex (only changed files)
curl -X POST http://localhost:8000/api/sources/documents/reindex

# Trigger full reindex (rebuild entire index from scratch)
curl -X POST "http://localhost:8000/api/sources/documents/reindex?full=true"

# Search
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"q": "kubernetes"}'
```

API docs available at http://localhost:8000/docs (when running backend directly; not proxied in Docker)

### Web UI (Phase 0 Scaffold)

The web UI at http://localhost:8000 shows the design direction for Phase 1:
- **Search page** - Search interface with result previews
- **Admin → Sources** - Source management UI
- **Admin → Status** - Indexing status dashboard

Currently displays mock data. Full API integration coming in Phase 1.

---

## Project Structure

```
OneSearch/
├── backend/              # FastAPI application
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── services/    # Business logic
│   │   ├── extractors/  # Document parsers
│   │   └── db/          # Database models
│   ├── tests/           # Backend tests
│   └── pyproject.toml   # Python dependencies (uv/pip)
├── frontend/            # React application
│   ├── src/
│   │   ├── pages/       # Page components
│   │   ├── components/  # Reusable UI components
│   │   └── lib/         # Utilities
│   └── package.json
├── cli/                 # Command-line interface
│   ├── onesearch/       # CLI commands
│   └── pyproject.toml
├── docker-compose.yml   # Deployment configuration
└── .env.example         # Environment template
```

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow, coding standards, and branching guidelines.

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Node.js 18+ with npm
- Docker + Docker Compose

### Backend Development

```bash
cd backend

# Using uv (recommended)
uv sync
uv run uvicorn app.main:app --reload

# Or using pip
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### Frontend Development

```bash
cd frontend
npm install
npm run dev
```

Dev server: http://localhost:5173 (proxies API to backend)

### CLI Development

```bash
cd cli
pip install -e .
onesearch --help
```

### Running Tests

```bash
# Start Meilisearch (required for API tests)
docker-compose up -d meilisearch

# Backend tests
cd backend && uv run pytest

# Frontend lint/build check
cd frontend && npm run lint && npm run build
```

---

## Configuration

### Environment Variables

See `.env.example` for all available configuration options:

- `MEILI_MASTER_KEY` - Meilisearch API key (required)
- `DATABASE_URL` - SQLite database path
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `MAX_TEXT_FILE_SIZE_MB` - Max text file size to index (default: 10)
- `MAX_PDF_FILE_SIZE_MB` - Max PDF file size to index (default: 50)

### Source Configuration

Sources are configured via the CLI or API and stored in SQLite. Each source supports:

- **Include Patterns**: Comma-separated glob patterns (e.g., `**/*.md,**/*.txt`)
- **Exclude Patterns**: Files to ignore (e.g., `**/node_modules/**,**/.git/**`)

---

## Supported File Types (Phase 0)

| Type | Extensions | Features |
|------|------------|----------|
| Text | `.txt`, `.log`, `.conf`, `.cfg`, `.ini` | Full-text search, encoding detection |
| Markdown | `.md`, `.markdown` | Full-text search, YAML front-matter parsing |
| PDF | `.pdf` | Text extraction, metadata (title, author, pages) |

**Coming in Phase 1:** Office formats (`.docx`, `.xlsx`, `.pptx`), image EXIF data

---

## Troubleshooting

### Indexing is slow

- **Network mounts**: SMB/NFS will be slower than local storage
- **Large PDFs**: PDF extraction is slower than text files
- **Check logs**: `docker-compose logs -f onesearch`

### Search returns no results

1. Verify indexing completed: `onesearch status` or `curl http://localhost:8000/api/status`
2. Check for errors in failed files list
3. Verify Meilisearch is running: `docker-compose ps`

### Permission errors

- Ensure source mounts are readable by container user (UID 1000)
- Use `:ro` (read-only) flag on volume mounts when possible

### Out of memory

- Increase Docker memory limit (Docker Desktop settings)
- Reduce batch size (future config option)
- Exclude large files with exclude patterns

---

## Roadmap

### Phase 1 (Coming Soon)
- Automated scheduled indexing
- Office document support (.docx, .xlsx, .pptx)
- Document detail/preview page
- Basic authentication

### Phase 2
- Multi-user access control
- Saved searches
- Image EXIF extraction
- Semantic search (embeddings)

### Phase 3
- Cloud storage connectors (via rclone)
- Obsidian vault support
- Advanced filters and facets
- Export search results

## Architecture

OneSearch consists of:

1. **FastAPI Backend** - REST API, indexing orchestration, document extraction
2. **Meilisearch** - Fast search engine with typo tolerance
3. **SQLite** - Metadata and source configuration storage
4. **React Frontend** - Search and admin UI

All components run in Docker containers and communicate over a private network.

---

## Performance

**Expected performance on modest hardware (4 cores, 8GB RAM):**

- **Indexing**: 50-100 files/second (text/markdown), 10-20 files/second (PDFs)
- **Search**: Sub-second response for queries on millions of documents
- **Memory**: ~300-500MB for backend + Meilisearch
- **Storage**: Index uses ~10-50% of original data size

---

## Privacy & Security

- **No outbound connections** - All data stays local
- **No telemetry** - Zero tracking or analytics
- **Read-only mounts** - Source directories mounted read-only by default
- **Network isolation** - Meilisearch only accessible via private Docker network
- **Minimal attack surface** - Backend runs as non-root, frontend uses nginx:alpine

---

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-only).

### What this means

- You can freely use, modify, and distribute this software
- If you modify and deploy this software on a network server, you must make your source code available to users
- This ensures OneSearch remains free and open source for everyone
- See the [LICENSE](LICENSE) file for complete terms

### Dependencies

All dependencies use permissive licenses (MIT, BSD, Apache-2.0) compatible with AGPL-3.0.

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow, coding standards, and testing requirements.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/demigodmode/OneSearch/issues)
- **Discussions**: [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) (enable if desired)

---

**Built with:** Python, FastAPI, Meilisearch, React, TypeScript, Docker
