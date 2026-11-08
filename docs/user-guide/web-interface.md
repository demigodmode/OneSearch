# Web Interface

The web UI is split into the search page and a small admin area.

## Search page

`/` is where you search. The search box is intentionally first; filters sit underneath it.

You can:

- filter by source or file type
- page through results
- open result cards for previews
- use keyboard shortcuts like `Ctrl+K`, `Cmd+K`, `/`, arrows, and `Enter`

The page remembers display preferences from **Settings → Search** in your browser.

## Document page

`/document/{id}` shows the indexed document. Depending on the file type, this can be extracted text, rendered Markdown, code with highlighting, image previews, photo metadata, media metadata, EPUB details, comic page lists, or a metadata-only view.

If you opened the document from search, matching terms are highlighted where the preview supports it.

**Copy path** and **Download** sit at the top of the page. Markdown documents also get a **Rendered** / **Raw** switch. See [Document Preview](document-preview.md) for details.

## Sources

Use this page to add, edit, delete, and reindex sources. Each source has a **Reindex** button for the usual incremental run and a **Full reindex** button that clears the source from the index and rebuilds it from scratch, after a confirmation.

This is also where you set per-source schedules. Use container paths such as `/data/documents` when running in Docker, and use the **Test** button in the source form to confirm OneSearch can see and read the path before saving.

## Agents

This page only appears after you turn on **Enable remote agents** under **Settings → Remote Agents**. It's where you enroll, approve, disable and revoke agents. See [Remote agents](../administration/remote-agents.md).

## Status

Status shows API/search health and per-source indexing counts. Expand a source to inspect failed files.

The page refreshes automatically, which is useful during a long first index.

## Settings

Settings has two kinds of options. Appearance (Light, Dark, or System mode and the accent color) and the search page display options are saved in each browser, so members get them too. Admins also see the server-wide options:

- preview behavior and size limits
- indexing behavior for unsupported files, RAW metadata, media metadata, and GPS metadata

Indexing-related changes apply to future indexing. Run a full reindex if you want old documents refreshed with the new settings.
