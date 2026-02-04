# Changelog

All notable changes to OneSearch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Notes

Phase 1 features in progress. Authentication and scheduled indexing planned for v0.7.0.

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

[0.6.0]: https://github.com/demigodmode/OneSearch/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/demigodmode/OneSearch/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/demigodmode/OneSearch/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/demigodmode/OneSearch/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/demigodmode/OneSearch/releases/tag/v0.2.0
