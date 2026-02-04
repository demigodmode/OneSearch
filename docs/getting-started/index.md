# Getting Started

OneSearch is designed to be easy to deploy and run. Everything runs in Docker containers, so you don't need to install Python, Node.js, or anything else on your host system.

## Installation Options

### Pre-built Docker Images (Recommended)

Use pre-built images from GitHub Container Registry. This is the fastest way to get started - just download docker-compose.yml and you're ready.

[Installation Guide](installation.md)

### Build from Source

Clone the repository and build the images yourself. Useful for development or if you want to customize the code.

[Build Instructions](installation.md#option-2-build-from-source)

---

## Quick Start

Get OneSearch running in three steps:

```bash
# 1. Download configuration
mkdir onesearch && cd onesearch
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env

# 2. Set Meilisearch key (generate with: openssl rand -base64 32)
# Edit .env and add: MEILI_MASTER_KEY=your-key-here

# 3. Start it
docker-compose up -d
```

Access the web interface at http://localhost:8000

---

## After Installation

Once OneSearch is running, follow the [First-Time Setup](first-time-setup.md) guide to:

- Add your first source
- Configure include/exclude patterns
- Trigger indexing
- Run your first search

---

## System Requirements

### Minimum

- OS: Linux, macOS, or Windows with WSL2
- CPU: 2 cores
- RAM: 4GB
- Storage: 500MB for OneSearch plus 10-50% of your source data size for the index

### Recommended

- CPU: 4+ cores for faster indexing
- RAM: 8GB+ for large document collections
- Storage: SSD for better performance

### Software

- Docker 20.10 or later
- Docker Compose 2.0 or later

That's it - all other dependencies are bundled in the containers.

---

## Architecture

OneSearch consists of three main components running in Docker containers:

- **nginx** - Serves the React frontend and proxies API requests
- **Backend (FastAPI)** - Handles indexing and search requests
- **Meilisearch** - Fast search engine with typo tolerance

The backend talks to Meilisearch over a private Docker network, so Meilisearch isn't exposed to the host. SQLite stores source configurations and file metadata.

---

## Need Help?

Having trouble? Check the [Troubleshooting Guide](../administration/troubleshooting.md) or [open an issue on GitHub](https://github.com/demigodmode/OneSearch/issues).
