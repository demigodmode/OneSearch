# OneSearch

**Self-hosted, privacy-focused search for your homelab**

Search across all your files, documents, and notes from a single, unified interface. No cloud dependencies, no telemetry, just fast local search.

---

## Features (Phase 0)

- **Fast Full-Text Search** - Powered by Meilisearch with typo tolerance and relevance ranking
- **Multiple File Types** - Text, Markdown, and PDF support
- **Multiple Sources** - Index local directories, mounted NAS shares, or external drives
- **Incremental Indexing** - Only reindex changed files, not your entire library
- **Clean Web UI** - Search and admin interfaces built with React
- **Privacy First** - All data stays local, no outbound connections
- **Easy Deployment** - Single Docker Compose command to get started

---

## Quick Start

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

### Adding a Source

1. Navigate to **Admin → Sources**
2. Click **Add Source**
3. Fill in the details:
   - **Name**: Friendly name (e.g., "NAS Documents")
   - **Root Path**: Container path (e.g., `/data/nas_docs`)
   - **Include Patterns**: Glob patterns (e.g., `**/*.pdf,**/*.md`)
   - **Exclude Patterns**: Files to skip (e.g., `**/node_modules/**`)
4. Click **Save**

### Indexing Files

1. Go to **Admin → Sources**
2. Find your source in the list
3. Click **Reindex**
4. Monitor progress in **Admin → Status**

### Searching

1. Enter your search query in the main search box
2. Use filters to narrow results:
   - **Source**: Filter by specific source
   - **Type**: Filter by file type (text, markdown, pdf)
   - **Date**: Filter by last modified date
3. Click on a result to view details

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
│   └── requirements.txt
├── frontend/            # React application
│   ├── src/
│   │   ├── pages/       # Page components
│   │   ├── components/  # Reusable UI components
│   │   └── lib/         # Utilities
│   └── package.json
├── docker-compose.yml   # Deployment configuration
└── .env.example         # Environment template
```

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow, coding standards, and branching guidelines.

### Backend Development

1. **Set up Python virtual environment**
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run development server**
   ```bash
   uvicorn app.main:app --reload
   ```

3. **Access API docs**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

### Frontend Development

1. **Install dependencies**
   ```bash
   cd frontend
   npm install
   ```

2. **Run development server**
   ```bash
   npm run dev
   ```

3. **Access dev server**
   - Frontend: http://localhost:5173
   - Vite will proxy API requests to backend

### Running Tests

```bash
# Backend tests
cd backend
docker-compose up -d meilisearch  # required for API/search tests
pytest

# Frontend tests (coming soon)
cd frontend
npm test
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

Sources are configured via the Web UI and stored in SQLite. Each source supports:

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

1. Verify indexing completed: **Admin → Status**
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
- **Non-root containers** - Services run as unprivileged users
- **Network isolation** - Meilisearch only accessible via private Docker network

---

## License

License pending. A LICENSE file will be added before a public release (MIT recommended).

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow, coding standards, and testing requirements.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/demigodmode/OneSearch/issues)
- **Discussions**: [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) (enable if desired)

---

**Built with:** Python, FastAPI, Meilisearch, React, TypeScript, Docker
