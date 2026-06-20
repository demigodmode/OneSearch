# Markdown Files

Markdown files are indexed as `markdown` documents.

## Extensions

- `.md`
- `.markdown`
- `.mdown`
- `.mkd`

## What OneSearch extracts

OneSearch reads the Markdown body as searchable text and parses YAML front matter when present.

Title detection uses this order:

1. `title` in front matter
2. first `# Heading`
3. filename without extension

Common front matter fields are copied into metadata when present, including `tags`, `date`, `author`, and `description`.

Example:

```markdown
---
title: NAS notes
tags: [homelab, storage]
---

# NAS notes

Remember to check SMART status monthly.
```

## Preview

Markdown previews render as formatted content in the document page. Search terms are highlighted when you open a result from the search page.

## Limits

Markdown uses the text extraction limit shown in **Admin → Settings → Indexing**. `MAX_TEXT_FILE_SIZE_MB` provides the default value, and `TEXT_EXTRACTION_TIMEOUT` controls how long extraction can run.

If parsing fails, OneSearch falls back to indexing the filename/path instead of failing the whole source.
