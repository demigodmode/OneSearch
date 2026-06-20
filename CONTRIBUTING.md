# Contributing to OneSearch

Thanks for helping with OneSearch. Keep changes focused and easy to review. If a change affects users, update the docs and changelog with it.

`main` is protected, so use a branch and open a pull request.

## Prerequisites

- Python 3.10+ with [uv](https://docs.astral.sh/uv/)
- Node 22.13+ with npm
- Docker for a local Meilisearch container; Docker Compose for full-stack container checks

## Local setup

From the repo root:

```bash
uv sync
```

That installs the backend and CLI workspace packages plus shared test tools.

Run the backend API:

```bash
DATABASE_URL=sqlite:///./onesearch-dev.db \
MEILI_URL=http://localhost:7700 \
MEILI_MASTER_KEY=dev-meili-key \
SESSION_SECRET=dev-session-secret \
uv run uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000
```

For search/indexing to work in backend-only development, run Meilisearch separately with the same key:

```bash
docker run --rm -p 7700:7700 \
  -e MEILI_MASTER_KEY=dev-meili-key \
  getmeili/meilisearch:v1.12
```

If you run `docker compose up -d` instead, the default compose file builds the full OneSearch container and runs managed Meilisearch inside it. That is useful for stack testing, but it is not the same as running the backend process directly from your checkout.

Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs at <http://localhost:5173> and proxies API calls to <http://localhost:8000>.

## Tests and checks

Run the smallest useful check while working. Before a mixed backend/frontend/docs PR, run:

```bash
uv run pytest backend/tests cli/tests
cd frontend && npm run lint && npm run build
cd .. && mkdocs build --strict
```

For Docker-facing changes, also build the image:

```bash
docker build -t onesearch:dev .
```

Backend-only examples:

```bash
uv run pytest backend/tests/test_api.py -q
uv run pytest backend/tests/test_scanner.py -q
```

Docs-only changes should still pass:

```bash
mkdocs build --strict
```

## Pull requests

- Base PRs on `main`.
- Use a focused branch like `feature/document-download` or `fix/exclude-patterns`.
- Include tests for bug fixes and new behavior when practical.
- Update user docs for user-facing behavior changes.
- Add a `CHANGELOG.md` entry for release-worthy changes.

A PR description can be short. Say what changed, why it matters, and anything reviewers should pay attention to.

## Style

- Follow nearby code style instead of introducing a new pattern.
- Python uses the shared Ruff config in `pyproject.toml`.
- Frontend code should pass `npm run lint` and `npm run build`.
- Keep docs direct and useful. Avoid filler.
- Do not commit secrets or machine-specific config.

## License and copyright

By contributing to OneSearch, you agree that your contribution is licensed under AGPL-3.0-only.

New source files should include the matching header:

Python:

```python
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only
```

JavaScript/TypeScript:

```javascript
// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only
```

CSS:

```css
/* Copyright (C) 2025 demigodmode
 * SPDX-License-Identifier: AGPL-3.0-only
 */
```
