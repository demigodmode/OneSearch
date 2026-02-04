# Installation

This guide covers installing OneSearch using pre-built Docker images or building from source.

## Prerequisites

You'll need:

- Docker 20.10 or later
- Docker Compose 2.0 or later
- At least 4GB RAM and 2 CPU cores
- Storage for your search index (typically 10-50% of your source data size)

Check your versions:

```bash
docker --version
docker-compose --version
```

---

## Option 1: Pre-built Images (Recommended)

This is the fastest way to get started. The images are built automatically and published to GitHub Container Registry.

### Download configuration files

```bash
mkdir onesearch && cd onesearch

curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env
```

### Generate a Meilisearch master key

You need a secure random key to protect your Meilisearch instance:

**Linux/macOS:**
```bash
openssl rand -base64 32
```

**Windows (PowerShell):**
```powershell
-join (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

**Windows (Git Bash):**
```bash
openssl rand -base64 32
```

Edit `.env` and paste your key:

```env
MEILI_MASTER_KEY=your-generated-key-here
```

Keep this key secure. Don't commit it to version control.

### Update docker-compose.yml

Edit `docker-compose.yml` and change the `onesearch` service to use the pre-built image:

```yaml
services:
  onesearch:
    image: ghcr.io/demigodmode/onesearch:latest
    # Comment out the build section if present:
    # build: .
    ports:
      - "8000:8000"
    # ... rest stays the same
```

### Mount your source directories (optional)

If you want to index local directories, add volume mounts under the `onesearch` service:

```yaml
services:
  onesearch:
    volumes:
      - onesearch_data:/app/data
      - /path/to/your/documents:/data/documents:ro
      - /mnt/nas/files:/data/nas:ro
```

The `:ro` flag mounts volumes as read-only, which is recommended for safety.

Use the container path (like `/data/documents`) when adding sources later, not the host path.

### Start OneSearch

```bash
docker-compose up -d
```

### Verify it's running

Check that services started:

```bash
docker-compose ps
```

You should see `onesearch` and `meilisearch` running.

Check logs if something looks wrong:

```bash
docker-compose logs -f onesearch
```

### Access the web interface

Open http://localhost:8000 in your browser. You should see the OneSearch search page.

---

## Option 2: Build from Source

Build from source if you want to contribute, customize the code, or run unreleased features.

### Clone the repository

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch
```

### Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your Meilisearch master key (see Option 1 above for how to generate one).

### Add volume mounts (optional)

Edit `docker-compose.yml` to mount directories:

```yaml
services:
  onesearch:
    volumes:
      - onesearch_data:/app/data
      - /path/to/your/documents:/data/documents:ro
```

### Build and start

```bash
docker-compose up -d --build
```

This builds the unified OneSearch image (takes 5-10 minutes the first time), pulls Meilisearch, and starts everything.

Watch the logs:

```bash
docker-compose logs -f onesearch
```

Look for:
```
INFO:     Uvicorn running on http://0.0.0.0:8001
```

### Access the web interface

Open http://localhost:8000 in your browser.

---

## What Gets Installed

After installation you have:

- Web UI at http://localhost:8000
- Backend API at http://localhost:8000/api
- CLI tool (inside the container, or install separately)

---

## Next Steps

Now that OneSearch is installed:

- [Add your first source](first-time-setup.md) and run your first search
- [Install the CLI](../cli/installation.md) for command-line access (optional)
- [Configure volume mounts](../configuration/volume-mounts.md) for your directories

---

## Uninstalling

To remove OneSearch:

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (deletes indexed data, not your files)
docker-compose down -v

# Remove images
docker rmi ghcr.io/demigodmode/onesearch:latest
docker rmi meilisearch/meilisearch:latest
```

The `-v` flag deletes your search index and configurations. Your original files are never modified or deleted by OneSearch.
