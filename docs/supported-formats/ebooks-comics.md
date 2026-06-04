# EPUB & Comics

EPUB books are indexed as `epub`; CBZ comics are indexed as `comic`.

## EPUB

Supported extension:

- `.epub`

OneSearch reads the EPUB package metadata and spine text. It extracts common fields such as title, creator, language, publisher, date, and identifier when present.

Readable XHTML chapters in the spine are converted to plain searchable text. Cover images and other non-text items are skipped.

Setting:

```env
EPUB_EXTRACTION_MAX_SIZE_MB=100
```

## CBZ comics

Supported extension:

- `.cbz`

OneSearch lists image pages in natural sort order and reads `ComicInfo.xml` when present.

ComicInfo fields can include title, series, number, writer, publisher, year, and summary.

Setting:

```env
COMIC_EXTRACTION_MAX_SIZE_MB=100
```

## Failure behavior

Corrupt EPUB/CBZ files fall back to metadata-only indexing where possible. The failed extraction is recorded, but indexing continues for the rest of the source.
