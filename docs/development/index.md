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

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy
- **Frontend:** React 19, TypeScript, Vite, TanStack Query, Tailwind CSS 4
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
uv sync --all-packages
(cd backend && DATABASE_URL=sqlite:///../onesearch-dev.db uv run alembic upgrade head)
DATABASE_URL=sqlite:///./onesearch-dev.db uv run uvicorn app.main:app --app-dir backend --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker build -t onesearch:dev .
ONESEARCH_IMAGE=onesearch:dev docker compose up -d
```

`docker compose up -d` on its own pulls the published image.

See individual guides for detailed instructions.
