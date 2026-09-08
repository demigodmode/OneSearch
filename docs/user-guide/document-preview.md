# Document Preview

Click a search result to open the document page. OneSearch shows the indexed document plus whatever metadata it could safely extract.

## What you might see

The preview depends on the file type:

- text, code, and config files show readable extracted text
- Markdown renders as formatted content
- PDFs and Office files show extracted text and metadata
- long text can be split into preview pages
- images and browser-viewable formats can show authenticated previews
- RAW photos can show embedded JPEG previews when available
- photos can show camera/lens/exposure metadata
- audio and video can show ffprobe metadata
- EPUB files show book metadata and extracted text
- CBZ comics show page lists and ComicInfo metadata when present
- unsupported files show filename/path metadata if metadata-only indexing is enabled

## Remote files

For a remote source, the server keeps indexed text, metadata, and any image previews stored during indexing. Those remain available when the agent is offline, disabled, or revoked, as long as you keep the source.

Downloading the original file or generating a preview that was not stored during indexing requires an available agent. Reconnect an offline agent or enable a disabled one before retrying. Revocation cannot be undone. Embedded RAW previews are not supported for remote files.

See [Remote agents](../administration/remote-agents.md#health-and-access-states) for the status meanings and [removal options](../administration/remote-agents.md#backup-restore-and-removal) before deleting sources.

## Search highlights

When you open a result from the search page, OneSearch carries the query into the document page. Readable previews highlight matches and let you jump through them.

## Preview limits

Admins can disable previews or set size limits in **Admin → Settings → File Previews**.

RAW previews use embedded JPEGs when available. OneSearch does not decode RAW sensor data, which keeps previews fast and avoids a lot of format-specific trouble.

## If a preview is missing

A missing preview usually means one of these:

- previews are disabled
- the file is larger than the preview limit
- the file type has metadata but no readable preview
- the source file moved or was deleted after indexing
- a remote agent is unavailable and the preview was not stored during indexing
- the extractor could not read the file

The document page should still show basic file metadata when the indexed document exists.
