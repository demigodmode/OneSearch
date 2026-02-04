# Architecture

OneSearch is built on a straightforward architecture designed for self-hosting and ease of deployment.

## High-Level Overview

OneSearch consists of three main components running in Docker containers:

**nginx** serves the React frontend and proxies API requests to the backend. Users only interact with nginx on port 8000.

**Backend (FastAPI)** handles indexing and search requests. It walks your file system, extracts content from documents, and talks to Meilisearch.

**Meilisearch** is the search engine. It stores the full-text index and handles search queries with typo tolerance and relevance ranking.

All three communicate over a private Docker network. Meilisearch isn't exposed to the host, so it's only accessible from the backend.

## Container Layout

```
┌─────────────────────────────────────┐
│       onesearch container           │
│  ┌─────────────────────────────────┐│
│  │         supervisord             ││
│  │  ┌──────────┐  ┌─────────────┐  ││
│  │  │  nginx   │  │   uvicorn   │  ││
│  │  │  :8000   │  │   :8001     │  ││
│  │  │ frontend │  │   backend   │  ││
│  │  └──────────┘  └─────────────┘  ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      meilisearch container          │
│              :7700                  │
└─────────────────────────────────────┘
```

Supervisord manages both nginx and uvicorn inside the OneSearch container. This keeps deployment simple - one container for the app, one for search.

---

## Data Flow

Here's what happens when you index and search:

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

### Why This Design

**Incremental indexing** is key. Reindexing a large library is slow, so OneSearch tracks file metadata in SQLite. When you reindex, it only processes files that changed. This makes regular updates fast.

**Extractors are pluggable**. Each file type has its own extractor (text, markdown, PDF, Office docs). They all return the same normalized document structure, so adding new formats is straightforward.

**Meilisearch handles search**. We don't reinvent the wheel - Meilisearch is purpose-built for fast full-text search with typo tolerance and relevance ranking.

---

## Database Schema

OneSearch uses SQLite for metadata. Two main tables:

### sources

Stores source configurations.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | Primary key (user-defined or auto-generated) |
| name | TEXT | Display name |
| root_path | TEXT | Container path to index |
| include_patterns | TEXT | Comma-separated glob patterns |
| exclude_patterns | TEXT | Comma-separated glob patterns |
| total_files | INTEGER | Count of indexed files |
| last_indexed_at | DATETIME | Last reindex timestamp |

### indexed_files

Tracks all indexed files for incremental updates.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| source_id | TEXT | Foreign key to sources |
| path | TEXT | Full file path |
| size | INTEGER | File size in bytes |
| modified_at | DATETIME | File modified timestamp |
| indexed_at | DATETIME | When we indexed it |
| hash | TEXT | SHA256 hash of path (for document ID) |
| status | TEXT | success, failed, pending |
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

This lets users filter searches by source or file type.

---

## Extractor System

Extractors live in `backend/app/extractors/` and follow a simple pattern:

**base.py** defines the abstract `BaseExtractor` class. All extractors inherit from it.

**Concrete extractors:**
- **text.py** - Plain text files with encoding detection
- **markdown.py** - Markdown with YAML front-matter parsing
- **pdf.py** - PDFs using pypdf for text extraction
- **office.py** - Word, Excel, PowerPoint using python-docx, openpyxl, python-pptx

Each extractor:
- Takes a file path
- Returns a normalized `Document` object
- Has timeout protection (corrupt or huge files won't hang indexing)
- Handles errors gracefully (failed files get logged, indexing continues)

Adding new file format support means creating a new extractor and registering it in the factory.

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
│   ├── search.py        # POST /api/search
│   ├── sources.py       # CRUD for /api/sources
│   └── status.py        # GET /api/health, /api/status
├── services/            # Business logic
│   ├── indexer.py       # Orchestrates indexing
│   ├── scanner.py       # File system walker
│   └── search.py        # Meilisearch client wrapper
├── extractors/          # Document parsers
└── db/
    └── database.py      # SQLAlchemy setup
```

**Why this structure:**

**Separation of concerns** - API routes are thin handlers. Business logic lives in services. Database models separate from request schemas.

**Dependency injection** - FastAPI's DI system provides database sessions and services to route handlers.

**Consistent responses** - All API endpoints return similar JSON structures. Errors use FastAPI's exception handling.

---

## Frontend Structure

React SPA using functional components and hooks:

```
frontend/src/
├── main.tsx             # Entry point
├── App.tsx              # Router + TanStack Query provider
├── pages/
│   ├── SearchPage.tsx   # Main search (/)
│   ├── DocumentPage.tsx # Document preview
│   └── admin/
│       ├── SourcesPage.tsx   # Manage sources
│       └── StatusPage.tsx    # Indexing status
├── components/
│   ├── SearchBox.tsx
│   ├── ResultCard.tsx
│   ├── SourceForm.tsx
│   └── ui/              # shadcn/ui components
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

## Why These Choices

**Docker Compose** - Easy deployment, reproducible environments, no host dependencies.

**FastAPI** - Modern Python framework with async support, automatic OpenAPI docs, type hints.

**Meilisearch** - Purpose-built for full-text search. Faster than Elasticsearch for our use case, simpler to operate.

**SQLite** - Lightweight, no separate database server, perfect for homelabs. Metadata is small.

**React + TypeScript** - Type safety catches bugs early. Modern React hooks are simple and powerful.

**shadcn/ui** - Components copied into the project (not npm deps), so we control the code. Tailwind-based, accessible.

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
- CLI tool
- All dependencies

Supervisord manages both processes. One container, simple deployment.

Meilisearch runs in a separate container because it's an independent service with its own lifecycle.

---

## Next Steps

Want to contribute? Check out:

- [Backend Development](backend-dev.md) - How to develop the backend
- [Frontend Development](frontend-dev.md) - How to develop the frontend
- [Adding Extractors](adding-extractors.md) - Add support for new file types
- [Contributing Guide](contributing.md) - General contribution guidelines
