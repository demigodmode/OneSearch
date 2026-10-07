# Text, Code & Config Files

OneSearch indexes plain text, source code, and configuration files using the same text extractor. The document type determines how results appear in search filters.

## Document Types

### Text (`text`)

General plain text files.

| Extension | Notes |
|-----------|-------|
| `.txt`, `.text` | Plain text |
| `.log` | Log files |

### Code (`code`)

Source code and markup files. Indexed as full text. The title is the first non-empty line near the top of the file, with comment markers stripped, or the filename if there isn't a short enough line.

| Extensions | |
|------------|-|
| `.py`, `.pyw` | Python |
| `.js`, `.jsx`, `.mjs`, `.cjs` | JavaScript |
| `.ts`, `.tsx` | TypeScript |
| `.java` | Java |
| `.c`, `.cpp`, `.cc`, `.h`, `.hpp` | C/C++ |
| `.go` | Go |
| `.rs` | Rust |
| `.rb` | Ruby |
| `.php` | PHP |
| `.cs` | C# |
| `.swift` | Swift |
| `.kt` | Kotlin |
| `.css`, `.scss`, `.sass`, `.less` | Stylesheets |
| `.html`, `.htm` | HTML |
| `.sh`, `.bash`, `.zsh`, `.fish` | Shell scripts |
| `.sql` | SQL |
| `.r` | R |
| `.lua` | Lua |

### Config (`config`)

Configuration and data files.

| Extension | Notes |
|-----------|-------|
| `.yaml`, `.yml` | YAML |
| `.toml` | TOML |
| `.json` | JSON |
| `.xml` | XML |
| `.ini`, `.cfg`, `.conf`, `.config` | INI-style configs |
| `.env` | Environment files |

## Features

- Automatic encoding detection (UTF-8, Latin-1, etc.)
- Full-text indexing
- Filter by type (`text`, `code`, `config`) in the search UI
- Size limits configurable in **Admin → Settings → Indexing**; `MAX_TEXT_FILE_SIZE_MB` sets the default for new installs
