# User Guide

This guide covers everything you need to know about using OneSearch effectively.

## Main Topics

**[Adding Sources](adding-sources.md)** - Configure directories to index and search.

**[Searching](searching.md)** - Learn search syntax, filters, and tips for finding what you need.

**[Web Interface](web-interface.md)** - Navigate the web UI and use all its features.

**[Document Preview](document-preview.md)** - View full document content with syntax highlighting.

**[Scheduling](scheduling.md)** - Set up automatic scan schedules for your sources.

**[Understanding Indexing](indexing.md)** - How indexing works and how to optimize it.

---

## Common Workflows

### Daily Use

Search your documents, use filters to narrow results, and click results to preview content. The status page shows indexing progress and any errors.

### Adding New Content

After adding files to your source directories, trigger a reindex from **Admin → Sources**. Use incremental reindex (the default) for speed - OneSearch only processes changed files.

### Maintaining Your Index

Reindex sources when content changes. Check the status page for failed files and fix any issues (permissions, corrupt files, etc.). Adjust include/exclude patterns to skip irrelevant content.

---

## Supported File Types

OneSearch currently supports:

| Type | Extensions | Features |
|------|------------|----------|
| Text | .txt, .log, .conf, .cfg, .ini | Full-text search, encoding detection |
| Markdown | .md, .markdown | Full-text search, YAML front-matter parsing |
| PDF | .pdf | Text extraction, metadata |
| Word | .docx | Paragraph and table extraction |
| Excel | .xlsx | Cell values across all sheets |
| PowerPoint | .pptx | Slide text and speaker notes |

See [Supported Formats](../supported-formats/index.md) for details.

---

## Tips & Best Practices

### Organizing Sources

Create separate sources for different content types (Documents, Code, Notes, etc.). Use meaningful names - they appear in search filters. Mount directories read-only (`:ro` in Docker) for safety.

### Include/Exclude Patterns

Be specific about what to include. Exclude build artifacts, dependencies, and hidden files to reduce noise. Test your patterns by adding a source and checking what gets indexed.

### Searching Effectively

Use filters to narrow by source or file type. Meilisearch is typo-tolerant, so don't worry about exact spelling. Check highlighted snippets for context. Click results to see the full document.

### Performance

Incremental reindex is fast for regular updates. Full reindex rebuilds everything - use it sparingly. Exclude large files you don't need. SSD storage improves indexing and search speed.

---

## Interface Overview

### Search Page

The main page has a search box (press `Cmd/Ctrl + K` to focus it), filters for source and file type, and clickable result cards with highlighted snippets. Pagination lets you browse through results.

### Admin Section

**Sources**: Manage sources - add, edit, delete, and trigger reindexing.

**Status**: Monitor indexing progress, view per-source statistics, and check failed files.

See the [Web Interface Guide](web-interface.md) for details.

---

## Getting Help

Check the [Troubleshooting Guide](../administration/troubleshooting.md) for common issues.

For bugs or feature requests, open a [GitHub Issue](https://github.com/demigodmode/OneSearch/issues).

For questions or discussions, use [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions).

---

## Next Steps

- **[Adding Sources](adding-sources.md)** - Configure what to index
- **[Searching](searching.md)** - Master search features
- **[Web Interface](web-interface.md)** - Navigate the UI
- **[Document Preview](document-preview.md)** - View full content
- **[Scheduling](scheduling.md)** - Automatic scan schedules
- **[Understanding Indexing](indexing.md)** - How it works
