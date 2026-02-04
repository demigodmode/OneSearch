# Architecture

OneSearch system architecture overview.

!!! note "Coming Soon"
    Detailed architecture documentation coming soon.

## High-Level Architecture

```
┌─────────────────────────────────────┐
│       onesearch container           │
│  ┌─────────────────────────────────┐│
│  │         supervisord             ││
│  │  ┌──────────┐  ┌─────────────┐  ││
│  │  │  nginx   │  │   uvicorn   │  ││
│  │  │  :8000   │  │   :8001     │  ││
│  │  │ frontend │  │   backend   │  ││
│  │  │ + proxy  │  │   + cli     │  ││
│  │  └──────────┘  └─────────────┘  ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      meilisearch container          │
│              :7700                  │
└─────────────────────────────────────┘
```

## Components

- **nginx** - Serves frontend, proxies API
- **FastAPI Backend** - Indexing and search logic
- **Meilisearch** - Search engine
- **SQLite** - Metadata storage
- **React Frontend** - Web UI

## Data Flow

See the README for data flow diagrams.
