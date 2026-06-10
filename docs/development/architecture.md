# Architecture

OneSearch's default Docker setup runs as one container: nginx, the FastAPI backend, and managed Meilisearch supervised together. The legacy two-container setup is still available for installs that want external Meilisearch.

## High-Level Overview

OneSearch consists of three main runtime pieces:

**nginx** serves the React frontend and proxies API requests to the backend. Users only interact with nginx on port 8000.

**Backend (FastAPI)** handles indexing and search requests. It walks your file system, extracts content from documents, and talks to Meilisearch.

**Meilisearch** is the search engine. It stores the full-text index and handles search queries with typo tolerance and relevance ranking.

In the default managed setup, Meilisearch listens on `127.0.0.1:7700` inside the app container and is not exposed to the host.

## Container Layout

```
┌─────────────────────────────────────────────┐
│             onesearch container             │
│  ┌───────────────────────────────────────┐  │
│  │              supervisord              │  │
│  │  ┌──────────┐ ┌─────────┐ ┌────────┐  │  │
│  │  │  nginx   │ │ uvicorn │ │ meili  │  │  │
│  │  │  :8000   │ │ :8001   │ │ :7700  │  │  │
│  │  │ frontend │ │ backend │ │ local  │  │  │
│  │  └──────────┘ └─────────┘ └────────┘  │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

Supervisord manages nginx, uvicorn, and managed Meilisearch inside the OneSearch container. In legacy mode, Meilisearch runs as a separate container or external service instead.

---

## Data Flow

Indexing and search:

### Indexing Flow

1. User adds a source via the web UI, CLI, or API
2. Source configuration (name, path, patterns) gets stored in SQLite
3. User triggers reindex
4. Scanner walks the directory and applies glob patterns (include/exclude)
5. For each file:
   - Check if it changed by comparing modified time, size, and hash with the `indexed_files` table
   - If changed, extract content using the appropriate extractor
   - Send normalized document to Meilisearch
   - Update `indexed_files` table with metadata
6. Search queries go to Meilisearch, which returns results with highlighted snippets

Reindexing a large library is slow, so OneSearch tracks file metadata in SQLite and only processes files that changed. Each file type has its own extractor (text, markdown, PDF, Office docs) that returns the same normalized document structure. Meilisearch handles search: typo tolerance and relevance ranking out of the box.

---

## Database Schema

OneSearch uses SQLite for metadata. The main tables are:

### sources

Stores source configurations.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | Primary key (user-defined or auto-generated) |
| name | TEXT | Display name |
| root_path | TEXT | Container path to index |
| include_patterns | TEXT | JSON array of glob patterns, stored as text |
| exclude_patterns | TEXT | JSON array of glob patterns, stored as text |
| scan_schedule | TEXT | Cron expression or preset (`@hourly`, `@daily`, `@weekly`) |
| last_scan_at | DATETIME | Last completed scan timestamp |
| next_scan_at | DATETIME | Next scheduled scan timestamp |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

### indexed_files

Tracks all indexed files for incremental updates.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| source_id | TEXT | Foreign key to sources |
| path | TEXT | Full file path |
| size_bytes | INTEGER | File size in bytes |
| modified_at | DATETIME | File modified timestamp |
| indexed_at | DATETIME | When we indexed it |
| hash | TEXT | SHA256 hash of path (for document ID) |
| status | TEXT | success, failed, skipped |
| error_message | TEXT | Error if failed |

Unique constraint on `(source_id, path)` prevents duplicates.

---

## Meilisearch Document Schema

Every document in Meilisearch follows this structure:

```json
{
  "id": "source1--a1b2c3d4e5f6",
  "source_id": "source1",
  "source_name": "NAS Documents",
  "path": "/path/to/file.pdf",
  "basename": "file.pdf",
  "extension": "pdf",
  "type": "pdf",
  "size_bytes": 123456,
  "modified_at": 1732896000,
  "indexed_at": 1732896000,
  "content": "Full extracted text content...",
  "title": "Optional document title",
  "metadata": {}
}
```

**Document IDs** use the format `{source_id}--{sha256_hash[:12]}` where the hash is derived from the file path. This avoids Meilisearch character restrictions and prevents ID collisions.

**Searchable fields:** content, basename, path, title

**Filterable fields:** source_id, type, extension, modified_at

**Sortable fields:** modified_at, size_bytes, basename

---

## Extractor System

Extractors live in `backend/app/extractors/` and follow a simple pattern:

**base.py** defines the abstract `BaseExtractor` class. All extractors inherit from it.

**Concrete extractors:**
- **text.py** - Plain text files with encoding detection
- **markdown.py** - Markdown with YAML front-matter parsing
- **pdf.py** - PDFs using pypdf for text extraction
- **office.py** - Word, Excel, PowerPoint using python-docx, openpyxl, python-pptx
- **rtf.py**, **epub.py**, **subtitles.py**, **comic.py** - rich document and archive-like formats
- **images.py**, **media.py**, **metadata.py** - images, RAW photos, audio/video metadata, and metadata-only fallback

Each extractor:
- Takes a file path
- Returns a normalized `Document` object
- Has timeout protection (corrupt or huge files won't hang indexing)
- Handles errors gracefully (failed files get logged, indexing continues)

Adding new file format support means creating a new extractor and registering it with the extractor registry.

---

## Backend Structure

The FastAPI application is organized into layers:

```
backend/app/
├── main.py              # FastAPI app setup, CORS, static files
├── config.py            # Settings from environment variables
├── models.py            # SQLAlchemy ORM models
├── schemas.py           # Pydantic request/response schemas
├── api/                 # API route handlers
│   ├── auth.py          # setup/login/JWT endpoints
│   ├── preview.py       # authenticated document previews
│   ├── search.py        # POST /api/search, GET /api/documents/{id}
│   ├── settings.py      # app-level settings
│   ├── sources.py       # CRUD, path tests, reindex, clear-stale
│   └── status.py        # GET /api/status, GET /api/status/{source_id}
├── services/            # Business logic
│   ├── indexer.py       # Orchestrates indexing
│   ├── scanner.py       # File system walker
│   └── search.py        # Meilisearch client wrapper
├── extractors/          # Document parsers
└── db/
    └── database.py      # SQLAlchemy setup
```

API routes are thin handlers. Business logic lives in services, models stay separate from request schemas. FastAPI's DI system injects database sessions into route handlers.

---

## Frontend Structure

React SPA using functional components and hooks:

```
frontend/src/
├── main.tsx             # Entry point
├── App.tsx              # Router + providers
├── pages/
│   ├── SearchPage.tsx   # Main search (/)
│   ├── DocumentPage.tsx # Document preview
│   ├── LoginPage.tsx    # Login
│   ├── SetupPage.tsx    # First-run setup
│   └── admin/
│       ├── SourcesPage.tsx   # Manage sources
│       ├── StatusPage.tsx    # Indexing status
│       └── SettingsPage.tsx  # Appearance, preview, indexing, search settings
├── components/
│   ├── AdminLayout.tsx
│   ├── MainLayout.tsx
│   ├── ProtectedRoute.tsx
│   ├── OneSearchLogo.tsx
│   ├── document/        # document detail renderers
│   └── ui/              # shadcn-style components copied into the repo
├── contexts/            # auth, theme, and search settings contexts
├── hooks/               # API/query hooks
├── lib/
│   ├── api.ts           # API client (fetch wrappers)
│   └── utils.ts         # Utilities
└── types/
    └── api.ts           # TypeScript interfaces
```

**State management:**

**TanStack Query** (React Query) manages server state - search results, sources, status. It handles caching, refetching, and invalidation automatically.

**React hooks** (useState, useEffect) manage local UI state - form inputs, modals, etc.

No global state library needed. Server state lives in TanStack Query, UI state in component hooks.

---

## Performance Considerations

**Incremental indexing** is the most important optimization. Always check `indexed_files` before reprocessing.

**Extractor timeouts** prevent hanging on corrupt or huge files. Default is 30 seconds for PDFs, 5 seconds for text.

**Meilisearch batching** - Send documents in batches of 100-1000 for efficiency, not one at a time.

**Read-only mounts** - Recommend `:ro` flag on Docker volumes. OneSearch only reads files, never writes.

---

## Deployment

The unified Docker image contains everything:
- nginx (compiled frontend)
- uvicorn (backend)
- managed Meilisearch
- CLI tool
- runtime dependencies

Supervisord manages nginx, uvicorn, and Meilisearch. One container, simple deployment. Legacy external-Meilisearch installs can still run the search engine separately when needed.

---

## Next Steps

Want to contribute? Check out:

- [Backend Development](backend-dev.md) - How to develop the backend
- [Frontend Development](frontend-dev.md) - How to develop the frontend
- [Adding Extractors](adding-extractors.md) - Add support for new file types
- [Contributing Guide](contributing.md) - General contribution guidelines
