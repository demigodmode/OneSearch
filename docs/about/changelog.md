# Changelog

All notable changes to OneSearch are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The complete changelog is maintained in the repository: [View on GitHub](https://github.com/demigodmode/OneSearch/blob/main/CHANGELOG.md)

---

## Latest Changes

### [Unreleased]

**Added:**
- Office document support (Word, Excel, PowerPoint)
- Document preview page with syntax highlighting
- Markdown rendering in preview
- Configuration options for Office files

**Fixed:**
- Security vulnerabilities in pypdf and react-router-dom
- Dependabot alerts (urllib3, prismjs)
- Memory leak in keyboard event listener
- Error messages leaking internal details

**Changed:**
- Search results are now clickable cards
- Added Office file types to search filters

**Issues closed:** #51, #52

**Pull requests:** #49, #55, #56

---

## [0.5.0] - 2025-12-25

**Added:**
- Unified Docker image containing frontend, backend, and CLI
- GitHub Actions CI/CD for automated builds
- Multi-platform Docker builds (linux/amd64, linux/arm64)
- Pre-built images on GHCR and Docker Hub

**Changed:**
- Simplified docker-compose.yml to use single unified image
- Updated README with pre-built image installation instructions

**Pull requests:** #48

---

## [0.4.0] - 2025-12-24

**Added:**
- Complete React frontend with full API integration
  - SearchPage with debounced queries, filters, pagination, keyboard shortcuts
  - SourcesPage with full CRUD operations
  - StatusPage with health monitoring and per-source metrics
- shadcn/ui component library
- TypeScript API client with TanStack Query hooks
- React Router with layouts

**Changed:**
- Backend now reads version dynamically from pyproject.toml

**Fixed:**
- XSS vulnerability in search result snippets
- Filter injection in Meilisearch queries
- Crash on undefined failed_files
- Documentation accuracy issues

**Pull requests:** #37, #39, #40, #41

---

## [0.3.0] - 2025-12-19

**Added:**
- CLI enhancements:
  - Path validation for source add command
  - `--quiet` / `-q` global flag
  - Configuration info in health command

**Fixed:**
- Console quiet mode implementation

**Pull requests:** #36

---

## [0.2.0] - 2025-12-11

**Added:**
- Complete CLI implementation
  - Source management commands
  - Search command with filters
  - Status and health commands
  - Configuration management
  - Rich terminal output
  - JSON output mode for scripting

**Pull requests:** #34

---

## Version History

| Version | Release Date | Highlights |
|---------|--------------|------------|
| [Unreleased] | TBD | Office docs, preview page, security fixes |
| [0.5.0] | 2025-12-25 | Unified Docker image, CI/CD |
| [0.4.0] | 2025-12-24 | Complete web UI |
| [0.3.0] | 2025-12-19 | CLI enhancements |
| [0.2.0] | 2025-12-11 | CLI implementation |

---

## Upgrading

See the [Upgrading Guide](../getting-started/upgrading.md) for instructions on updating to the latest version.

---

[Unreleased]: https://github.com/demigodmode/OneSearch/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/demigodmode/OneSearch/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/demigodmode/OneSearch/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/demigodmode/OneSearch/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/demigodmode/OneSearch/releases/tag/v0.2.0
