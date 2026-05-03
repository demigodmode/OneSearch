# OneSearch

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Latest Release](https://img.shields.io/github/v/release/demigodmode/OneSearch)](https://github.com/demigodmode/OneSearch/releases/latest)
[![Tests](https://img.shields.io/github/actions/workflow/status/demigodmode/OneSearch/backend-tests.yml?label=tests)](https://github.com/demigodmode/OneSearch/actions/workflows/backend-tests.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/demigodmode/onesearch)](https://hub.docker.com/r/demigodmode/onesearch)
[![Documentation](https://readthedocs.org/projects/onesearch/badge/?version=latest)](https://onesearch.readthedocs.io)

Search your homelab like you search the web.

OneSearch indexes your local directories, NAS shares, and external drives and gives you instant full-text search from a browser. No cloud, no telemetry, runs in Docker.

![OneSearch search results](assets/screenshots/search_results.png)

---

## Quick Start

```bash
mkdir onesearch && cd onesearch
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env
```

Edit `.env` and set `MEILI_MASTER_KEY` to a random string (`openssl rand -base64 32` works).

```bash
docker-compose up -d
```

Open http://localhost:8000, run through the setup wizard, add a directory as a source, and start searching.

> **Heads up:** OneSearch is moving toward an easier single-container setup. The default install still runs Meilisearch as a separate container, but v0.13 adds an opt-in managed Meilisearch mode where OneSearch starts Meilisearch inside the app container. If you want to try it, use `docker-compose.managed-meili.yml`; existing installs should read the [migration guide](https://onesearch.readthedocs.io/en/latest/getting-started/migrate-to-managed-meilisearch/) first. Existing installs do not need to change.

Full setup guide: [onesearch.readthedocs.io](https://onesearch.readthedocs.io/en/latest/getting-started/installation/)

---

## What it indexes

| Type | Formats |
|------|---------|
| Documents | PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) |
| Markdown | .md, .markdown |
| Code | .py, .js, .ts, .go, .rs, .java, .c, .cpp, .sh, .sql, [and more](https://onesearch.readthedocs.io/en/latest/supported-formats/text-files/) |
| Config | .yaml, .toml, .json, .xml, .ini, .env, [and more](https://onesearch.readthedocs.io/en/latest/supported-formats/text-files/) |
| Text | .txt, .log |

Incremental indexing so only changed files get reindexed. Per-source cron schedules so your NAS gets scanned daily without thinking about it.

---

## Screenshots

Document preview with metadata and syntax highlighting:

![Document preview](assets/screenshots/document_preview.png)

Admin panel - indexing status across all sources:

![Admin status](assets/screenshots/admin_status.png)

Accent color theming - pick what feels like yours:

![Admin settings](assets/screenshots/admin_settings.png)

---

## Documentation

**[onesearch.readthedocs.io](https://onesearch.readthedocs.io)**

- [Installation Guide](https://onesearch.readthedocs.io/en/latest/getting-started/installation/)
- [User Guide](https://onesearch.readthedocs.io/en/latest/user-guide/)
- [CLI Reference](https://onesearch.readthedocs.io/en/latest/cli/) - standalone `onesearch-cli` package that connects to your running OneSearch server and ships from the same tagged release as the Docker image
- [API Reference](https://onesearch.readthedocs.io/en/latest/api/)

---

## Development

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch
```

See the [Development Guide](https://onesearch.readthedocs.io/en/latest/development/) for setup instructions.

---

## License

[AGPL-3.0](LICENSE). Free to use, modify, and distribute. If you deploy a modified version as a network service, source must be made available.

---

## Support

- [GitHub Issues](https://github.com/demigodmode/OneSearch/issues) - bugs and feature requests
- [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) - questions and ideas
- [Documentation](https://onesearch.readthedocs.io) - guides and reference
