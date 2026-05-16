# Understanding Indexing

How OneSearch indexes your files.

!!! note "Coming Soon"
    Detailed indexing documentation coming soon.

## Key Concepts

- **Incremental Indexing** - Only changed files are reindexed
- **Full Reindex** - Rebuild entire index from scratch
- **File Metadata** - Tracks modified time, size, hash
- **Metadata-only indexing** - Unsupported files can still be indexed by filename, path, source, extension, size, and modified time
- **Optional probes** - RAW photo metadata uses exiftool when available; media metadata uses ffprobe when available

See [First-Time Setup](../getting-started/first-time-setup.md#incremental-vs-full-reindex) for basics.

!!! tip "Changing indexing settings"
    Settings such as unsupported-file behavior, RAW metadata extraction, GPS metadata, and extraction size limits apply to future indexing. Run a full reindex if existing documents need to be refreshed with new settings.
