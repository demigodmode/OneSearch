# Testing

Run the smallest useful check while working, then the broader checks before you push.

## Backend

From the repo root, after `uv sync --all-packages`:

```bash
uv run pytest backend/tests
```

Focused examples:

```bash
uv run pytest backend/tests/test_api.py -v
uv run pytest backend/tests/test_api.py::TestSearchEndpoint::test_search_with_filters -v
uv run pytest backend/tests/test_extractors.py -v
```

Use pytest for API, service, scheduler, config, and extractor coverage. Extractor tests should include real-ish sample files where possible, but keep fixtures small.

## CLI

From the repo root:

```bash
uv run pytest cli/tests
```

The CLI tests cover command behavior, config handling, auth flow, and API client behavior.

## Agent and shared

```bash
uv run pytest agent/tests shared/tests
```

`agent/tests` covers the remote agent. `shared/tests` covers the protocol and path code that the server and the agent both use. CI runs the agent tests on Linux and Windows.

## Frontend

From `frontend/`:

```bash
npm run lint
npm test
npm run build
```

`npm test` runs the Vitest suite once. Use `npm run test:watch` while working. Test files sit next to the code they cover as `*.test.ts` or `*.test.tsx`.

## Docs

From the repo root:

```bash
mkdocs build --strict
```

This catches broken nav and many bad links. If you use a temporary output directory while checking docs, remove it before committing.

## Full pre-PR pass

For mixed changes, run:

```bash
uv run pytest backend/tests cli/tests agent/tests shared/tests
cd frontend && npm run lint && npm test && npm run build
cd .. && mkdocs build --strict
```

You do not need to run everything for a tiny docs-only edit, but do run the docs build.
