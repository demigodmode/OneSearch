# Metadata-only Files

Unsupported files can still be indexed as `file` documents when metadata-only indexing is enabled.

## What gets indexed

OneSearch stores searchable text made from:

- filename
- absolute path inside the container
- source name
- extension
- file size
- modified time

No file contents are read.

## Setting

```env
UNSUPPORTED_FILE_POLICY=metadata_only
```

Options:

- `metadata_only`: index unknown files by filename/path metadata
- `skip`: ignore unknown files

You can also change this in **Admin → Settings → Indexing**.

## When this helps

Metadata-only indexing is useful for archives, installers, CAD files, design files, or any format OneSearch does not understand yet. You can still find the file by name or folder even without full-text extraction.

Run a full reindex after changing this setting if you want existing sources updated.
