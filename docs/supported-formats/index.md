# Supported File Formats

OneSearch supports searchable text extraction, format metadata, and safe previews for common document and media libraries.

## Currently Supported

| Format | Type | Extensions | Features |
|--------|------|------------|----------|
| **Plain Text** | `text` | .txt, .log | Encoding detection, full-text search |
| **Code** | `code` | .py, .js, .ts, .go, .rs, .java, .c, .cpp, .sh, .css, .html, .sql, [more…](text-files.md) | Full-text search, title from first line |
| **Config** | `config` | .yaml, .yml, .toml, .json, .xml, .ini, .env, [more…](text-files.md) | Full-text search |
| **Markdown** | `markdown` | .md, .markdown | YAML front-matter, rendered preview, full-text search |
| **PDF** | `pdf` | .pdf | Text extraction, metadata |
| **Word** | `docx` | .docx | Paragraphs, tables, metadata |
| **Excel** | `xlsx` | .xlsx | All sheets, cell values |
| **PowerPoint** | `pptx` | .pptx | Slides, speaker notes |
| **RTF** | `rtf` | .rtf | Readable text extraction |
| **EPUB** | `epub` | .epub | Book metadata, ordered spine text |
| **Subtitles** | `subtitle` | .srt, .vtt, .ass | Transcript extraction, cue counts |
| **Comics** | `comic` | .cbz | Page listing, ComicInfo.xml metadata |
| **Images** | `image` | .jpg, .jpeg, .png, .webp, .gif, .tif, .tiff | Dimensions, EXIF metadata, authenticated previews |
| **RAW Photos** | `raw_image` | .cr2, .cr3, .nef, .arw, .raf, .orf, .rw2, .dng | Optional exiftool metadata, embedded JPEG previews |
| **Media** | `media` | .mp4, .mkv, .mov, .avi, .mp3, .flac, .m4a, .ogg, .wav | Optional ffprobe metadata |
| **Unsupported files** | `file` | any other extension | Optional filename/path metadata-only indexing |

## Rich Media Notes

- RAW metadata extraction uses `exiftool` when available. The Docker image includes it; non-Docker installs can leave it unavailable and RAW files will still index with basic metadata.
- Media metadata extraction uses `ffprobe` when available. If it is missing or fails, media files fall back to filename/path metadata instead of failing the whole index run.
- GPS photo metadata is off by default. Enable it in Admin → Settings → Indexing only if you want location data searchable.
- Image and RAW previews are served only for indexed documents, require authentication, and respect the preview size limits in Admin → Settings → File Previews.
- Changing indexing settings affects future indexing. Run a full reindex if you want existing documents updated with new metadata behavior.

## Format Details

- [Text, Code & Config Files](text-files.md)
- [Markdown](markdown.md)
- [PDF Documents](pdf.md)
- [Office Documents](office-documents.md)

## Still Planned

- Archive file contents beyond CBZ comics (.zip, .tar.gz)
- Email (.eml, .mbox)
- OCR for scanned/image-only documents

See the [Roadmap](../about/roadmap.md) for planned formats.
