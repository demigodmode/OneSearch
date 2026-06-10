# Web Interface

The web UI is split into the search page and a small admin area.

## Search page

`/` is where you search. The search box is intentionally first; filters sit underneath it.

You can:

- filter by source or file type
- page through results
- open result cards for previews
- use keyboard shortcuts like `Ctrl+K`, `Cmd+K`, `/`, arrows, and `Enter`

The page remembers display preferences from **Admin → Settings → Search** in your browser.

## Document page

`/document/{id}` shows the indexed document. Depending on the file type, this can be extracted text, rendered Markdown, code with highlighting, image previews, photo metadata, media metadata, EPUB details, comic page lists, or a metadata-only view.

If you opened the document from search, matching terms are highlighted where the preview supports it.

## Admin → Sources

Use this page to add, edit, delete, and reindex sources.

This is also where you set per-source schedules. Use container paths such as `/data/documents` when running in Docker, and use the Root Path **Test** button to confirm OneSearch can see and read the path before saving.

## Admin → Status

Status shows API/search health and per-source indexing counts. Expand a source to inspect failed files.

The page refreshes automatically, which is useful during a long first index.

## Admin → Settings

Settings is where app-level preferences live:

- Light, Dark, or System appearance mode plus theme accent
- preview behavior and size limits
- indexing behavior for unsupported files, RAW metadata, media metadata, and GPS metadata
- search page display preferences

Indexing-related changes apply to future indexing. Run a full reindex if you want old documents refreshed with the new settings.
