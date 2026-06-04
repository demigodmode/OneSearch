# Testing

Run the smallest useful check while working, then the broader checks before you push.

## Backend

From `backend/`:

```bash
uv run pytest
```

Focused examples:

```bash
uv run pytest tests/test_api.py -v
uv run pytest tests/test_search_service.py::test_search_with_filters -v
uv run pytest tests/test_extractors.py -v
```

Use pytest for API, service, scheduler, config, and extractor coverage. Extractor tests should include real-ish sample files where possible, but keep fixtures small.

## CLI

From `cli/`:

```bash
uv run pytest
```

The CLI tests cover command behavior, config handling, auth flow, and API client behavior.

## Frontend

From `frontend/`:

```bash
npm run lint
npm run build
```

There is no large frontend test suite at the moment, so lint and production build are the baseline checks.

## Docs

From the repo root:

```bash
mkdocs build --strict
```

This catches broken nav and many bad links. If you use a temporary output directory while checking docs, remove it before committing.

## Full pre-PR pass

For mixed changes, run:

```bash
cd backend && uv run pytest
cd ../cli && uv run pytest
cd ../frontend && npm run lint && npm run build
cd .. && mkdocs build --strict
```

You do not need to run everything for a tiny docs-only edit, but do run the docs build.
