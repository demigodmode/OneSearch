# Searching

The search page is the front door of OneSearch. Type a query, filter if needed, and click a result to open the document view.

## Basic search

Go to `/` and start typing. Searches are debounced, so results update shortly after you pause.

Meilisearch handles typo tolerance and relevance ranking. You usually do not need exact filenames or exact casing.

Keyboard shortcuts:

- `Ctrl+K` / `Cmd+K`: focus the search box
- `/`: focus the search box when you are not already typing somewhere
- `Escape`: clear or blur the search box
- arrow keys: move through results
- `Enter`: open the selected result

## Filters

Use the dropdowns above the results to narrow things down.

**Source** filters to one configured source, like `Documents` or `Photos`.

**Type** filters to one indexed document type. Current choices include text, Markdown, code, config, PDF, Office documents, RTF, EPUB, subtitles, comics, images, RAW images, media, and metadata-only files.

Click **Clear filters** to go back to everything.

## Result cards

Each result shows the filename, path, snippet, source, type, size, and modified date depending on your display settings.

Snippets use highlighted `<em>` matches from the search engine. For long documents, the snippet is just context. Open the result for the full preview.

## Search settings

Go to **Admin → Settings → Search** to tune the search page:

- results per page
- sort order
- snippet length
- compact or spacious result density
- whether to show path, size, date, and metadata

Those are browser preferences, so changing them does not reindex files.

## Search from the CLI

```bash
onesearch search "kubernetes deployment"
onesearch search "invoice" --source documents
onesearch search "readme" --type markdown --limit 10
onesearch search "error" --json
```

The CLI currently supports `text`, `markdown`, and `pdf` for `--type`. The web UI and API support the full type list.

## Search from the API

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"q": "kubernetes", "limit": 10}'
```

See the [Search API](../api/search.md) page for the full request shape.
