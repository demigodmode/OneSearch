# Backup & Restore

Backup and restore your OneSearch data.

!!! note "Coming Soon"
    Comprehensive backup guide coming soon.

## Quick Backup

Backup the data volume:

```bash
docker run --rm -v onesearch_data:/data -v $(pwd):/backup alpine tar czf /backup/onesearch-backup.tar.gz /data
```

## What to Backup

- SQLite database (metadata and source configs)
- Meilisearch index data

Your **original files are never modified** by OneSearch.
