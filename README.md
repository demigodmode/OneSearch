# OneSearch

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Documentation](https://img.shields.io/badge/docs-ReadTheDocs-blue)](https://onesearch.readthedocs.io)

Self-hosted, privacy-focused search for your homelab.

Search across all your files, documents, and notes from a single interface. No cloud dependencies, no telemetry, just fast local search.

---

## Features

- Fast full-text search powered by Meilisearch
- Multiple file types: text, markdown, PDF, and Office documents (Word, Excel, PowerPoint)
- Index local directories, NAS shares, or external drives
- Incremental indexing (only changed files get reindexed)
- Document preview with syntax highlighting
- Web UI, REST API, and CLI
- Privacy first - all data stays local

---

## Quick Start

```bash
# Create project directory
mkdir onesearch && cd onesearch

# Download configuration
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env

# Generate Meilisearch key
openssl rand -base64 32
# Add to .env: MEILI_MASTER_KEY=your-key-here

# Edit docker-compose.yml to use pre-built image:
# image: ghcr.io/demigodmode/onesearch:latest

# Start OneSearch
docker-compose up -d
```

Open http://localhost:8000 and start searching.

**For detailed installation instructions, see the [documentation](https://onesearch.readthedocs.io/en/latest/getting-started/installation/).**

---

## Documentation

Full documentation is available on ReadTheDocs:

**[https://onesearch.readthedocs.io](https://onesearch.readthedocs.io)**

- [Installation Guide](https://onesearch.readthedocs.io/en/latest/getting-started/installation/) - Detailed setup instructions
- [User Guide](https://onesearch.readthedocs.io/en/latest/user-guide/) - Adding sources, searching, and managing your index
- [CLI Documentation](https://onesearch.readthedocs.io/en/latest/cli/) - Command-line interface reference
- [API Reference](https://onesearch.readthedocs.io/en/latest/api/) - REST API documentation
- [Development Guide](https://onesearch.readthedocs.io/en/latest/development/) - Contributing and architecture

---

## Supported File Types

| Type | Extensions |
|------|------------|
| Text | .txt, .log, .conf, .cfg, .ini |
| Markdown | .md, .markdown |
| PDF | .pdf |
| Word | .docx |
| Excel | .xlsx |
| PowerPoint | .pptx |

---

## Architecture

OneSearch is built on modern, proven technologies:

- **Backend**: FastAPI (Python) with async support
- **Search**: Meilisearch for fast full-text search
- **Database**: SQLite for metadata
- **Frontend**: React + TypeScript
- **Deployment**: Docker Compose

See the [Architecture Guide](https://onesearch.readthedocs.io/en/latest/development/architecture/) for details.

---

## Development

Want to contribute?

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch
```

See the [Development Guide](https://onesearch.readthedocs.io/en/latest/development/) for setup instructions.

---

## License

Licensed under [AGPL-3.0](LICENSE). You can freely use, modify, and distribute OneSearch. If you deploy a modified version as a network service, you must make your source code available.

See the [License Documentation](https://onesearch.readthedocs.io/en/latest/about/license/) for details.

---

## Support

- [Documentation](https://onesearch.readthedocs.io) - Full guides and references
- [GitHub Issues](https://github.com/demigodmode/OneSearch/issues) - Bug reports and feature requests
- [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) - Questions and ideas

---

**Built with Python, FastAPI, Meilisearch, React, TypeScript, Docker**
