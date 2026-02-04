# Development Overview

Welcome to OneSearch development documentation!

## Quick Links

- [Contributing Guide](contributing.md)
- [Architecture](architecture.md)
- [Backend Development](backend-dev.md)
- [Frontend Development](frontend-dev.md)
- [Adding File Extractors](adding-extractors.md)
- [Testing](testing.md)

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy
- **Frontend:** React 18, TypeScript, Vite, TanStack Query
- **Search:** Meilisearch
- **Database:** SQLite
- **Deployment:** Docker, Docker Compose

## Getting Started

1. Clone the repository
2. Read [Contributing Guide](contributing.md)
3. Set up development environment
4. Pick an issue or feature to work on

## Development Commands

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker-compose up -d --build
```

See individual guides for detailed instructions.
