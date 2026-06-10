# Changelog

All notable changes to OneSearch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-06-10

### Added

- Added source path preflight testing so users can check a root path before saving it. The test reports whether OneSearch can see the path, whether it is inside allowed roots, whether it exists, whether it is a directory, and whether the container can read it. (#183)
- Added clearer Docker path guidance in the source form and docs, including host-path hints for common `/mnt/...` and Windows drive-letter mistakes. (#183)
- Added Light, Dark, and System appearance modes in Settings while preserving accent color presets and custom hue controls. (#38)
- Added a friendlier custom interval scan schedule UI for minutes, hours, and days, while keeping advanced cron available for power users. (#131)
- Added Podman deployment notes covering `podman compose`, rootless permissions, SELinux labels, and container source paths.

### Changed

- Softened the focused search box border and glow so keyboard focus is visible without overpowering the page. (#132)
- Clarified that custom interval schedules currently run on cron clock boundaries. (#131)
- Fully qualified Docker Hub base images in the Dockerfile so Docker builds still work and stricter Podman installs do not rely on short-name registry configuration.

### Fixed

- Fixed relative schedule times in the UI by treating API timestamps without timezone suffixes as UTC.
- Fixed custom interval schedule editing so saved interval cron patterns reopen as interval controls instead of dropping users into advanced cron. (#131)
- Fixed the custom interval number field so it can be cleared normally while still validating before save. (#131)

---

## [1.0.5] - 2026-06-08

### Changed

- Upgraded frontend linting to ESLint 10 and migrated from `.eslintrc.cjs` to flat config.
- Updated the Docker frontend build stage to Node 22 for ESLint 10 tooling compatibility.
- Upgraded frontend build tooling to Vite 8 and @vitejs/plugin-react 6.
- Preserved the lazy-loaded DocumentPage split by keeping markdown and syntax-highlighter packages out of the eager React vendor chunk under Vite 8.
- Hardened EPUB and CBZ extraction with uncompressed archive entry limits and clean metadata-only fallback for oversized compressed archives.

---

## [1.0.4] - 2026-06-07

### Changed

- Upgraded lucide-react to v1, react-syntax-highlighter to v16, eslint-plugin-react-hooks to 7.1, and TypeScript to 6 for focused frontend dependency compatibility.
- Added narrow React Hooks lint exceptions for intentional auth/bootstrap and settings draft synchronization effects.
- Added TypeScript 6 deprecation handling for the existing frontend path alias configuration.

---

## [1.0.3] - 2026-06-07

### Changed

- Updated focused frontend dependencies for Radix UI, TanStack Query, date-fns, tailwind-merge, TypeScript ESLint, autoprefixer, and PostCSS while leaving major framework/tooling migrations for separate tracked issues.
- Updated the MkDocs git revision date plugin requirement to allow 1.5.3.

---

## [1.0.2] - 2026-06-06

### Added

- Added Docker `PUID` and `PGID` support so the runtime user can match host users or shared groups for mounted volumes.

### Fixed

- Fixed live-source indexing crashes when a file disappears after scanning but before extraction.
- Fixed Meilisearch indexing failures caused by datetime values in nested document metadata.
- Improved malformed Markdown frontmatter handling so the markdown body is still indexed as plain content.

---

## [1.0.1] - 2026-06-04

### Security

- Updated `react-router` and `react-router-dom` to 6.30.4 for the protocol-relative redirect advisory.
- Updated FastAPI and Starlette so Starlette is 1.0.1, fixing the Host header/request URL path advisory.

---

## [1.0.0] - 2026-06-03

### Added

- Added `docker-compose.legacy.yml` for existing and advanced installs that want to keep Meilisearch as a separate service.

### Changed

- Managed Meilisearch is now the default Docker deployment. New installs use a single OneSearch container with the search engine managed internally.
- The default `docker-compose.yml` now stores the bundled Meilisearch index in `onesearch_index:/app/meili_data`.
- The legacy external Meilisearch compose setup remains supported, but is no longer the recommended new-install path.
- Installation, upgrade, and migration docs now distinguish new managed installs from existing two-container installs.

---

## [0.15.1] - 2026-06-03

### Security

- Updated `idna` to address CVE-2026-45409 / GHSA-65pc-fj4g-8rjx.
- Hardened source path validation so paths outside configured allowed roots are rejected before filesystem existence/type checks.
- Added canonical path validation for source roots to guard against symlink escapes from allowed directories.
- Replaced raw internal exception details in status and Meilisearch health fallbacks with generic client-facing messages while preserving server-side logging.

### Changed

- Removed unused Codecov upload from backend CI while keeping local coverage output in test logs.
- Updated documentation and GitHub Actions maintenance dependencies.

---

## [0.15.0] - 2026-05-16

### Added

- Added RTF indexing with readable text extraction.
- Added EPUB indexing with book metadata and ordered spine text extraction.
- Added subtitle indexing for SRT, WebVTT, and ASS/SSA files.
- Added CBZ comic indexing with page counts, naturally sorted page lists, and ComicInfo.xml metadata.
- Added image indexing for JPG, PNG, WebP, GIF, TIFF, and related browser-viewable image formats.
- Added RAW photo indexing for CR2, CR3, NEF, ARW, RAF, ORF, RW2, and DNG files.
- Added optional RAW metadata extraction via exiftool, including camera make/model, lens, ISO, aperture, exposure, focal length, dimensions, and date taken.
- Added optional media metadata indexing for audio/video files with ffprobe when available.
- Added metadata-only indexing for unsupported file types so unknown files can still be found by filename, path, source, extension, size, and modified time.
- Added authenticated image previews on document detail pages.
- Added RAW embedded JPEG previews, including support for selecting the largest embedded JPEG when RAW files contain multiple thumbnails/previews.
- Added format-aware document detail views for photos, RAW images, media files, comics, EPUB, RTF, and subtitles.
- Added photo metadata cards for camera, lens, ISO, aperture, exposure, focal length, date taken, and dimensions.
- Added media metadata cards for title, artist, album, date, duration, codecs, bitrate, dimensions, frame rate, sample rate, and channels when available.
- Added comic detail cards and page listings for CBZ files.
- Added long text preview pagination for large extracted text documents.
- Added search match highlighting and match navigation in readable document previews.
- Added Admin Settings controls for Appearance, File Previews, Indexing, and Search.
- Added configurable preview and extraction limits for image/RAW metadata, media probing, EPUB extraction, CBZ extraction, long text pagination, and readable preview page size.
- Added settings for unsupported-file behavior, RAW metadata extraction, media metadata extraction, GPS metadata indexing, image previews, RAW previews, and preview size limits.
- Added native tooltips for search filters, settings controls, source form fields, and source actions.
- Added rich media document type filters to search.

### Changed

- Search filters now show by default instead of only after typing a query.
- Search type filtering now includes RTF, EPUB, subtitles, comics, images, RAW images, media, and metadata-only files.
- Settings are organized into compact Appearance, File Previews, Indexing, and Search sections.
- GPS metadata remains disabled by default and must be explicitly enabled before photo location metadata is indexed.
- Optional media and RAW metadata probing now fall back cleanly to metadata-only indexing when tools are unavailable or probing fails.
- Docker runtime now includes exiftool so container installs can extract RAW metadata in Auto mode.
- Large or unsupported image/RAW files now fall back to metadata-only indexing instead of failing the whole indexing run.
- Existing document preview behavior is preserved for text, markdown, code, PDF, and Office documents.

### Fixed

- Fixed RAW previews that used a tiny embedded thumbnail when a larger embedded preview was also available.
- Fixed RAW metadata coverage for RAW files that Pillow can identify but exiftool can describe more completely.
- Fixed preview handling for live Meilisearch document objects.
- Fixed long text pagination for very large single-block or newline-heavy text content.
- Fixed subtitle parser edge cases around cue blocks, WEBVTT notes/styles, and ASS override text.
- Fixed RTF unicode escape handling.
- Fixed EPUB extraction so non-text spine items such as cover images are skipped.
- Fixed CBZ page sorting so numbered pages sort naturally.
- Fixed image metadata fallback behavior for oversized, unreadable, or unsupported image files.

---

## [0.14.0] - 2026-05-06

### Added

- Added full reindex support to the CLI and Admin Sources UI for managed Meilisearch migrations or index repair.

### Fixed

- Full reindex now validates that the source path exists before clearing existing index metadata.

### Changed

- Updated managed Meilisearch migration docs to require full reindexing after cutover.

---

## [0.13.2] - 2026-05-06

### Fixed

- Cache-busted the favicon link so browsers stop showing the old tab icon after the logo update.

---

## [0.13.1] - 2026-05-06

### Changed

- Added the new OneSearch logo to the README, browser favicon, and app header. The in-app logo now follows the active accent hue.
- Cleaned up frontend context exports and localStorage initialization so the full frontend lint check passes again.

---

## [0.13.0] - 2026-05-03

### Added

- **Managed Meilisearch mode** - added an opt-in single-container mode where OneSearch starts Meilisearch inside the app container. Existing two-container installs keep working as before, and the docs now include a safe migration guide.
- **Meilisearch contract coverage** - added a live integration test against Meilisearch v1.12 so client/API mismatches are caught earlier.

### Fixed

- **Source cleanup in Meilisearch** - replaced the unsupported delete-by-filter client call with the supported `delete_documents(..., filter=...)` API.
- **Bundled Meilisearch on ARM64** - fixed the Dockerfile so the bundled Meilisearch binary works on both amd64 and ARM64 builds.

---

## [0.12.1] - 2026-04-23

### Fixed

- **Release automation** - fixed the shared release workflow so GitHub can start it cleanly again, and pinned `eslint-plugin-react-refresh` to an ESLint 8-compatible version so Docker image builds no longer fail during `npm ci`.

---

## [0.12.0] - 2026-04-23

### Added

- **Standalone CLI auth flow** - `onesearch login`, `logout`, and `whoami` now support interactive username/password login for humans and direct token storage for scripts.
- **Live CLI startup panel** - bare `onesearch` now shows a Rich startup banner with backend URL, auth state, server status, version mismatch hints, and actionable first-run guidance.
- **CLI integration tests** - added Python-level auth integration coverage for login, token reuse, and unauthenticated `whoami` behavior.

### Changed

- **Shared release pipeline** - the Docker image and `onesearch-cli` package now build from the same tagged release workflow and stay on the same version.
- **CLI CI verification** - CI now runs CLI tests and builds the `onesearch-cli` distribution artifacts on normal pushes and pull requests.
- **CLI docs** - installation, configuration, and examples now describe the standalone package as the primary UX and Docker `exec` as the fallback path.

---

## [0.11.1] - 2026-03-25

### Fixed

- **Stale failed files** - files deleted or moved after scanning were stuck in the Failed Files list indefinitely. The indexer now handles `FileNotFoundError` mid-index and lets the normal deletion logic clean them up. A "Clear stale" button on the Status page lets you manually flush existing stale entries.

### Security

- Bumped pypdf 6.9.0 → 6.9.2 (inefficient stream decoding, CVE)
- Bumped flatted 3.3.3 → 3.4.2 (prototype pollution)
- Upgraded @typescript-eslint 6.x → 8.x (minimatch ReDoS)

### Maintenance

- Added CodeQL scanning for Python and TypeScript
- Added Dependabot version update config for pip, npm, and GitHub Actions

---

## [0.11.0] - 2026-03-21

### Added

- **Search settings** - configurable results per page, sort order, snippet length, display density, and metadata visibility. All preferences persist to localStorage. New "Search" section in Admin -> Settings with segmented buttons, toggles, and a sort dropdown.
- **Keyboard shortcuts** - `/` or `Ctrl+K` (`Cmd+K` on Mac) to focus search, `Escape` to clear or blur, arrow keys to navigate results, `Enter` to open. Shortcut hint in the search box now shows the correct modifier for your OS.
- **Backend sort and snippet length** - search API accepts `sort` (validated against allowed fields) and `snippet_length` (50-1000) parameters. Sort is passed through to Meilisearch; snippet length controls both the crop and the response truncation.

### Fixed

- **Search box focus ring** - removed the 1px spread that was overlapping the search icon. Focus state now uses only the soft glow.
- **Flaky timestamp test** - `test_update_source_success` was comparing `updated_at != created_at`, which fails when both happen within the same millisecond. Changed to `>=`.

---

## [0.10.0] - 2026-03-18

### Added

- **Accent color theming** - OneSearch has now cycled through cyan, indigo, and amber in the span of three releases. Rather than shipping a fourth opinion, this release lets you pick. Five presets (Amber, Indigo, Cyan, Teal, Rose) plus a 0-360 hue slider for the truly indecisive. Find it in Admin -> Settings. Choice persists to localStorage and is applied before first paint via an inline script, so no amber flash if you're an indigo person.

---

## [0.9.1] - 2026-03-14

### Changed

- **Brand color switched to amber** - replaced indigo accent with warm amber, warm-tinted neutral backgrounds to match. CSS-only change via custom properties.

---

## [0.9.0] - 2026-03-14

### Changed

- **UI redesign** — full design audit pass. Replaced cyan accent palette with indigo, removed all glow/shimmer effects, dropped the hero section (search box is now the first element), replaced StatusPage metric cards with a compact inline status bar.
- **Container queries** — SourcesPage table and DocumentPage metadata grid now respond to their container width instead of the viewport. Columns were toggling at the wrong breakpoints due to the admin sidebar taking ~224px.
- **Lazy-loaded DocumentPage** — split off into its own chunk via `React.lazy`. Switched from full Prism to PrismLight with explicit language registration, significantly reducing the initial bundle.
- **Release script** — `scripts/release.py` handles version bumps across all 5 files, CHANGELOG promotion, git tag, push, and GitHub release creation in one command.
- **Backend tests on all PRs** — removed path filter from CI so the required check always runs and doesn't block merges on frontend-only PRs.

### Fixed

- **Accessibility** — added `aria-label` to the search input, 44px minimum touch targets on sources table action buttons, focus rings on interactive elements, `prefers-reduced-motion` support.
- **CLI version drift** — CLI package was stuck at 0.7.x while the rest of the project was at 0.8.0.

---

## [0.8.0] - 2026-03-08

Code and config files are now searchable by type, plus a security update for pypdf.

### Added

- **Code and config file types** — `.py`, `.js`, `.go`, `.sh` etc are now indexed as `code`; `.yaml`, `.toml`, `.json`, `.env` etc as `config`. Both show up as filter options in the search UI. (#102)
- **More supported extensions** — `.mjs`, `.cjs`, `.cs`, `.swift`, `.kt`, `.fish`, `.lua`, `.env` added to the indexer.
- **3 new extractor tests** — covering type classification for code, config, and plain text files.

### Changed

- **Extension → type is now a single dict** — previously three separate lists had to be kept in sync. Now `SUPPORTED_EXTENSIONS` is derived automatically from the type map; one place to edit.

### Security

- **pypdf 6.6.2 → 6.7.5** — fixes several CVEs where malformed PDFs could exhaust RAM or cause infinite loops. (#106)

### Issues Closed

- #102, #106

---

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

Milestone 1 complete. All core features are in — search, indexing, auth, scheduling, document preview.

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

[1.1.0]: https://github.com/demigodmode/OneSearch/compare/v1.0.5...v1.1.0
[1.0.5]: https://github.com/demigodmode/OneSearch/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/demigodmode/OneSearch/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/demigodmode/OneSearch/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/demigodmode/OneSearch/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/demigodmode/OneSearch/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/demigodmode/OneSearch/compare/v0.15.1...v1.0.0
[0.15.1]: https://github.com/demigodmode/OneSearch/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/demigodmode/OneSearch/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/demigodmode/OneSearch/compare/v0.13.2...v0.14.0
[0.13.2]: https://github.com/demigodmode/OneSearch/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/demigodmode/OneSearch/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/demigodmode/OneSearch/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/demigodmode/OneSearch/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/demigodmode/OneSearch/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/demigodmode/OneSearch/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/demigodmode/OneSearch/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/demigodmode/OneSearch/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/demigodmode/OneSearch/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/demigodmode/OneSearch/compare/v0.8.0...v0.9.0
[0.7.1]: https://github.com/demigodmode/OneSearch/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/demigodmode/OneSearch/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/demigodmode/OneSearch/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/demigodmode/OneSearch/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/demigodmode/OneSearch/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/demigodmode/OneSearch/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/demigodmode/OneSearch/releases/tag/v0.2.0
