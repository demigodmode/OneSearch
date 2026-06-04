# Backup & Restore

OneSearch never modifies your original files. Backups are about the app database, settings, and search index.

## What to back up

For the default managed Docker setup:

- `onesearch_data`: SQLite database, source config, app data
- `onesearch_index`: managed Meilisearch index data
- your `.env`
- your `docker-compose.yml`, especially source mounts

Your actual documents/photos/NAS files should already be covered by your normal backup process.

## Before backing up

Stop the container first so SQLite and Meilisearch are quiet:

```bash
docker compose down
```

Then list the actual volume names Docker created:

```bash
docker volume ls
```

Compose usually prefixes volume names with the project directory. For example, a directory named `onesearch` might create `onesearch_onesearch_data` and `onesearch_onesearch_index`.

## Back up named volumes

Replace the volume names below with the names from `docker volume ls`:

```bash
docker run --rm \
  -v onesearch_onesearch_data:/data:ro \
  -v "$PWD:/backup" \
  alpine tar czf /backup/onesearch-data.tar.gz -C /data .

docker run --rm \
  -v onesearch_onesearch_index:/index:ro \
  -v "$PWD:/backup" \
  alpine tar czf /backup/onesearch-index.tar.gz -C /index .
```

Also copy your config files:

```bash
cp .env docker-compose.yml ./backup-copy/
```

Start OneSearch again when finished:

```bash
docker compose up -d
```

## Restore

Stop OneSearch:

```bash
docker compose down
```

Create volumes if they do not already exist:

```bash
docker volume create onesearch_onesearch_data
docker volume create onesearch_onesearch_index
```

Restore the tarballs:

```bash
docker run --rm \
  -v onesearch_onesearch_data:/data \
  -v "$PWD:/backup" \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/onesearch-data.tar.gz -C /data"

docker run --rm \
  -v onesearch_onesearch_index:/index \
  -v "$PWD:/backup" \
  alpine sh -c "rm -rf /index/* && tar xzf /backup/onesearch-index.tar.gz -C /index"
```

Put `.env` and `docker-compose.yml` back, then start:

```bash
docker compose up -d
```

## If you only have the database

You can restore only `onesearch_data` and skip the Meilisearch index. After startup, run a full reindex for each source. It takes longer, but it rebuilds the search index from your original files.
