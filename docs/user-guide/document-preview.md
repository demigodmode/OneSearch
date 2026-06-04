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
- the extractor could not read the file

The document page should still show basic file metadata when the indexed document exists.
