# Contributing to OneSearch

Thanks for your interest in OneSearch! This project protects `main` with branch rules—please work in feature branches and open pull requests for review.

## Prerequisites
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Node 18+ with npm
- Docker + Docker Compose (for Meilisearch and containerized dev)

## Local Development

### Backend
```bash
cd backend

# Using uv (recommended)
uv sync
uv run uvicorn app.main:app --reload

# Or using pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```
API docs: http://localhost:8000/docs

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

## License and Copyright

By contributing to OneSearch, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-only).

### Developer Certificate of Origin

By submitting a pull request, you certify that:

1. The contribution was created in whole or in part by you and you have the right to submit it under the AGPL-3.0-only license; or
2. The contribution is based upon previous work that, to the best of your knowledge, is covered under an appropriate open source license and you have the right under that license to submit that work with modifications, whether created in whole or in part by you, under the AGPL-3.0-only license; or
3. The contribution was provided directly to you by some other person who certified (1) or (2) and you have not modified it.
4. You understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information you submit with it) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.

### Copyright Headers

All new source files must include the following copyright header at the top:

**Python files:**
```python
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only
```

**JavaScript/TypeScript files:**
```javascript
// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only
```

**CSS files:**
```css
/* Copyright (C) 2025 demigodmode
 * SPDX-License-Identifier: AGPL-3.0-only
 */
```
