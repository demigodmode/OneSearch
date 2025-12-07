# Contributing to OneSearch

Thanks for your interest in OneSearch! This project protects `main` with branch rules—please work in feature branches and open pull requests for review.

## Prerequisites
- Python 3.13+
- Node 18+ with npm
- Docker + Docker Compose (for Meilisearch and containerized dev)

## Local Development

### Backend
1. `cd backend`
2. Create a virtualenv: `python -m venv .venv && source .venv/bin/activate`
3. Install deps (including test extras): `pip install -e .[dev]`
4. Run the API: `uvicorn app.main:app --reload`
   - API docs: http://localhost:8000/docs

### Frontend
1. `cd frontend`
2. Install deps: `npm install`
3. Start dev server: `npm run dev` (http://localhost:5173)

## Testing
- Start Meilisearch for API tests: `docker-compose up -d meilisearch`
- Backend tests: `cd backend && pytest`
- Frontend lint/build: `cd frontend && npm run lint && npm run build`

## Pull Requests
- Base branch: `main`; use `feature/<topic>` or `fix/<issue>` branches.
- Keep PRs focused and include tests for new behavior and regressions.
- Update docs (README/local_docs) when you change user-facing behavior.
- Ensure CI passes before requesting review.

## Style & Standards
- Python: target `py311`, line length 100 (see `pyproject.toml`); match existing style.
- JS/TS: follow project eslint/prettier defaults (via `npm run lint`).
- Security: do not commit secrets; prefer environment variables.
