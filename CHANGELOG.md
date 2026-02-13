# Changelog

All notable changes to OneSearch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.3] - 2026-02-13

Small fixes and better test coverage.

### Fixed

- **Schedule display updates immediately** — changing a source's scan schedule (e.g. daily → hourly) now updates the "Next: in Xh" text right away instead of requiring a page refresh. (#101)

### Added

- **Custom favicon** — replaced the default Vite logo with a proper OneSearch icon (cyan search icon). (#103)
- **Scheduler tests** — 24 new tests covering `validate_schedule`, `resolve_cron`, `calculate_next_run_time`
- **Source scheduling API tests** — 8 new tests for `next_scan_at` behavior on create/update

### Issues Closed

- #101, #103

---

## [0.7.2] - 2026-02-07

Big hardening pass based on a thorough code review. Auth actually works now, endpoints are protected, and a bunch of security/performance/UX issues are cleaned up.

### Security

- **Enforce auth on all API endpoints** — search, sources, status endpoints now require a valid JWT. Previously auth was decorative — JWT existed but nothing checked it. (#71)
- **CORS is now configurable** — set `CORS_ORIGINS` env var instead of allowing all origins. Empty = same-origin only (the default for Docker deployments). (#73)
- **Source path restriction** — new `ALLOWED_SOURCE_PATHS` env var (default: `/data`) prevents adding sources from arbitrary filesystem paths. (#75)
- **Don't leak error details** — reindex errors now return a generic message instead of internal stack traces. (#76)
- **Don't log database URL** — health endpoint and startup logs no longer expose the full DB connection string. (#77, #88)

### Fixed

- **SQLite check_same_thread** — only applied when actually using SQLite, so Postgres/MySQL work too. (#72)
- **SQLite WAL pragma** — now attached to the engine instance instead of globally, so it works correctly with connection pooling. (#87)
- **Rate limiter memory leak** — stale IPs are now pruned every 5 minutes instead of accumulating forever. (#81)
- **Health endpoint returns 503** — when Meilisearch is unreachable, health now returns 503 instead of 200 with errors buried in the response body. (#86)
- **chown /app/data on startup** — entrypoint.sh now fixes ownership before running migrations, preventing permission errors on mounted volumes. (#74)
- **Remove stale Dockerfiles** — backend/Dockerfile and frontend/Dockerfile were leftover from before the unified build. Removed. (#91)
- **Remove test bind mount** — docker-compose.yml had an uncommented `./local_docs` mount that would fail on fresh installs. (#90)

### Performance

- **SQL aggregation for source status** — replaced Python-side counting of all IndexedFile rows with proper SQL COUNT/CASE queries. (#78)
- **SQL count for source deletion** — replaced loading all indexed files into memory just to count them. (#79)

### Frontend

- **401 auto-redirect** — expired tokens now clear auth state and redirect to login instead of showing a broken page. (#82)
- **Search state restoration** — back-navigation from document view restores your search query and filters via URL params. (#83)
- **Mutation error reset** — stale error banners in source add/edit dialogs now clear when reopening. (#84)
- **Login page loading order** — loading spinner now shows before checking auth state, preventing a flash of the login form. (#85)
- **Admin index redirect** — `/admin` now redirects to `/admin/sources` instead of showing a blank page. (#93)
- **404 catch-all** — unknown routes redirect to home instead of showing a blank page. (#94)
- **Clipboard error handling** — copy-path button no longer throws on non-HTTPS contexts. (#95)
- **Dynamic version display** — admin sidebar now shows version from package.json instead of hardcoded v0.3.0. (#92)
- **Removed asyncio.set_event_loop** — was unnecessary and could cause issues with concurrent requests. (#80)

### Nginx

- **Proxy API docs** — `/docs`, `/redoc`, `/openapi.json` are now proxied to the backend. (#89)

### Issues Closed

- #71 through #95

---

## [0.7.1] - 2026-02-07

Hotfix for critical deployment bugs found during first real Proxmox CT install. The app basically couldn't start in Docker.

### Fixed

- **SQLite URL path format** — default DATABASE_URL used 3 slashes (relative path) instead of 4 (absolute path), so SQLAlchemy couldn't find `/data/onesearch.db`. Fixed everywhere: config.py, docker-compose.yml, .env.example, docs. Also fixed the path itself from `/data/` to `/app/data/` to match the Dockerfile. (#69)

- **Alembic hardcoded database path** — alembic.ini had a hardcoded `sqlalchemy.url` that could conflict with the DATABASE_URL env var. Removed it — env.py already sets the URL programmatically from app settings. (#68)

- **APScheduler pickle crash when adding sources** — the SQLAlchemy job store tried to pickle scheduled jobs, but bound methods referencing the engine can't be pickled. Switched to in-memory job store since `_sync_all_jobs` already rebuilds everything from the Source table on startup. (#70)

### Issues Closed

- #68, #69, #70

---

## [0.7.0] - 2026-02-05

Phase 1 complete. All core features are in — search, indexing, auth, scheduling, document preview.

### Added

- **Basic Authentication** - JWT-based auth with setup wizard, login page, protected routes, rate limiting. Config: `SESSION_SECRET`, `SESSION_EXPIRE_HOURS`, `AUTH_RATE_LIMIT`.

- **Scheduled Indexing** - APScheduler-based background indexing with per-source cron schedules. Presets (@hourly, @daily, @weekly) or custom cron expressions. Per-source locking prevents concurrent indexing (409 on conflict). Config: `SCHEDULER_ENABLED`, `SCHEDULE_TIMEZONE`.
  - Schedule picker in source add/edit form
  - Schedule column and next scan time in sources table
  - Next scan info on status page

### Fixed

- **Security: Replaced python-jose with PyJWT** - python-jose depends on ecdsa which has an unfixed timing attack vulnerability (CVE-2024-23342). PyJWT does not have this dependency.

### Dependencies

- bcrypt, PyJWT (authentication)
- APScheduler (scheduled indexing)

### Issues Closed

- #50 - Scheduled indexing
- #53 - Basic authentication

### Pull Requests

- #57 - Add basic authentication
- #60 - Scheduled indexing with APScheduler

---

## [0.6.0] - 2026-02-04

### Added

- **Office Document Support** - Added extractors for Microsoft Office formats
  - `.docx` (Word) - extracts paragraphs, tables, and metadata
  - `.xlsx` (Excel) - extracts all cell values across sheets
  - `.pptx` (PowerPoint) - extracts slide text and speaker notes
  - New config options: `MAX_OFFICE_FILE_SIZE_MB`, `OFFICE_EXTRACTION_TIMEOUT`
  - Better error handling for password-protected and corrupted files

- **Document Preview Page** - Click any search result to view full content
  - Syntax highlighting for code files via Prism.js
  - Markdown rendering with code block support
  - Keyboard shortcut: Escape to return to search
  - Clickable search result cards

### Fixed

- **Security Vulnerabilities** (PR #49)
  - Updated `pypdf` to >=6.6.2 (fixes CVE-2026-24688: infinite loop in bookmarks)
  - Updated `python-multipart` to >=0.0.22 (fixes CVE-2026-24486: path traversal vulnerability)
  - Updated `react-router-dom` to ^6.30.3 (fixes HIGH severity XSS via open redirects in @remix-run/router)

- **Dependabot Security Alerts** (PR #56)
  - Updated `urllib3` to 2.6.3 (fixes CVE: decompression bomb safeguards bypass)
  - Override `prismjs` to 1.30.0 (fixes DOM Clobbering vulnerability)

- Memory leak in keyboard event listener cleanup
- Error messages that leaked internal implementation details
- Resource cleanup for Excel file extraction

### Changed

- Search results are now clickable cards instead of static displays
- Added Office file types (docx, xlsx, pptx) to the search filter dropdown

### Dependencies

- python-docx, openpyxl, python-pptx (backend)
- react-markdown, react-syntax-highlighter (frontend)

### Issues Closed

- #51 - Office document extractors
- #52 - Document detail/preview page

### Pull Requests

- #49 - fix: Update dependencies to address security vulnerabilities
- #55 - Office doc support + document preview page
- #56 - fix: Address Dependabot security alerts

---

## [0.5.0] - 2025-12-25

### Added

- **Unified Docker Image** - Single `onesearch` image containing frontend, backend, and CLI
  - Multi-stage Dockerfile for optimized builds (~410MB)
  - Supervisord manages nginx + uvicorn processes
  - Pre-built images available on GHCR and Docker Hub

- **GitHub Actions CI/CD** - Automated Docker image builds on release
  - Publishes to `ghcr.io/demigodmode/onesearch`
  - Publishes to `docker.io/demigodmode/onesearch`
  - Multi-platform builds (linux/amd64, linux/arm64)
  - Semantic versioning tags (e.g., `0.5.0`, `0.5`, `latest`)

### Changed

- Simplified docker-compose.yml to use single unified image
- Updated README with pre-built image installation instructions

### Closes

- #47 - Unified Docker image with GitHub Actions CI/CD

### Pull Requests

- #48 - feat: Unified Docker image with GitHub Actions CI/CD

---

## [0.4.0] - 2025-12-24

### Added

- **Web UI** - Complete React frontend with full API integration
  - **SearchPage** - Real search with debounced queries, source/type filters, pagination, highlighted snippets, keyboard shortcut (Cmd+K)
  - **SourcesPage** - Full CRUD operations for sources with add/edit/delete dialogs, reindex button with progress indicator
  - **StatusPage** - Health monitoring with API server status, Meilisearch connection, aggregate stats, per-source metrics, expandable failed files list
  - Auto-refresh polling (30 seconds) via TanStack Query
  - Loading skeletons, error states, and empty states throughout

- **UI Components** - shadcn/ui component library with 10 core components (Button, Input, Dialog, Card, Badge, Table, Select, Label, Alert, Separator)

- **API Client** - TypeScript API client with TanStack Query hooks for all endpoints

- **React Router** - Client-side routing with MainLayout and AdminLayout

### Changed

- Backend now reads version dynamically from `pyproject.toml` via `importlib.metadata`
- All package versions synchronized to 0.4.0

### Fixed

- XSS vulnerability in search result snippets (sanitized HTML)
- Filter injection in Meilisearch queries (escaped with `json.dumps`)
- Crash on undefined `failed_files` in status responses
- Documentation accuracy issues (ports, install commands, Docker paths)

### Closes

- #15 - React Router and TanStack Query setup
- #16 - SearchPage implementation
- #17 - SourcesPage implementation
- #18 - StatusPage implementation
- #19 - shadcn/ui components
- #22 - README and user documentation
- #23 - API client and hooks
- #24 - Backend tests

### Pull Requests

- #37 - feat(frontend): Setup React frontend scaffold with routing and state
- #39 - feat(frontend): Add shadcn/ui components and API client
- #40 - docs: Fix documentation accuracy issues
- #41 - feat(frontend): Implement SearchPage, SourcesPage, and StatusPage

---

## [0.3.0] - 2025-12-19

### Added

- **CLI Enhancements**
  - Path validation for `source add` command (use `--no-validate` for Docker container paths)
  - `--quiet` / `-q` global flag to suppress non-essential output
  - Configuration info displayed in `health` command

### Fixed

- `Console(quiet=True)` invalid parameter - now uses `io.StringIO` for quiet mode

### Closes

- #29 - CLI source management commands
- #30 - CLI search command
- #31 - CLI status and health commands
- #32 - CLI configuration and polish

### Pull Requests

- #36 - fix(cli): Address minor gaps in CLI implementation

---

## [0.2.0] - 2025-12-11

### Added

- **CLI Implementation** - New command-line interface for OneSearch
  - `onesearch source list|add|show|delete|reindex` - Manage search sources
  - `onesearch search <query>` - Full-text search with filters
  - `onesearch status [source_id]` - View indexing status
  - `onesearch health` - System health check
  - `onesearch config show|get|set|init` - Manage CLI configuration
  - Rich terminal output with tables and colors
  - JSON output mode (`--json`) for scripting
  - Cross-platform config file support
  - Environment variable support (`ONESEARCH_URL`)

### Closes

- #28 - Setup CLI package scaffold
- #29 - CLI source management commands
- #30 - CLI search command
- #31 - CLI status and health commands
- #32 - CLI configuration and polish

### Pull Requests

- #34 - feat: Implement CLI for OneSearch

---

[0.7.1]: https://github.com/demigodmode/OneSearch/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/demigodmode/OneSearch/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/demigodmode/OneSearch/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/demigodmode/OneSearch/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/demigodmode/OneSearch/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/demigodmode/OneSearch/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/demigodmode/OneSearch/releases/tag/v0.2.0
