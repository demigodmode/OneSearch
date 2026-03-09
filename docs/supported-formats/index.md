# Supported File Formats

OneSearch supports multiple file formats with specialized extractors.

## Currently Supported

| Format | Type | Extensions | Features |
|--------|------|------------|----------|
| **Plain Text** | `text` | .txt, .log | Encoding detection, full-text search |
| **Code** | `code` | .py, .js, .ts, .go, .rs, .java, .c, .cpp, .sh, .css, .html, .sql, [more…](text-files.md) | Full-text search, title from first line |
| **Config** | `config` | .yaml, .yml, .toml, .json, .xml, .ini, .env, [more…](text-files.md) | Full-text search |
| **Markdown** | `markdown` | .md, .markdown | YAML front-matter, full-text search |
| **PDF** | `pdf` | .pdf | Text extraction, metadata |
| **Word** | `docx` | .docx | Paragraphs, tables, metadata |
| **Excel** | `xlsx` | .xlsx | All sheets, cell values |
| **PowerPoint** | `pptx` | .pptx | Slides, speaker notes |

## Format Details

- [Text, Code & Config Files](text-files.md)
- [Markdown](markdown.md)
- [PDF Documents](pdf.md)
- [Office Documents](office-documents.md)

## Coming Soon

- Image metadata (EXIF)
- Archive files (.zip, .tar.gz)
- Email (.eml, .mbox)

See the [Roadmap](../about/roadmap.md) for planned formats.
