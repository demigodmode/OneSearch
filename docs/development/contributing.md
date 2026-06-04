# Contributing

Thanks for helping with OneSearch. Small, focused changes are easiest to review.

## Before you start

Check existing issues and discussions so you do not duplicate work. For bigger changes, open an issue first and describe the use case.

## Local setup

Backend and frontend setup live in separate guides:

- [Backend Development](backend-dev.md)
- [Frontend Development](frontend-dev.md)

Quick version:

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch
```

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Before opening a PR

Run the checks that match your change.

Backend:

```bash
cd backend
uv run pytest
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

Docs:

```bash
mkdocs build --strict
```

## PRs

Keep PRs focused. If you changed user-facing behavior, update docs and add a `CHANGELOG.md` entry.

A good PR description can be short. Just tell reviewers what changed and anything they should pay attention to.

## Style notes

- Follow the surrounding code style.
- Prefer clear tests over clever tests.
- Do not add broad refactors to feature/bugfix PRs unless they are needed.
- Keep docs practical. Avoid marketing copy and empty filler.

## Questions

Use [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) for questions and [GitHub Issues](https://github.com/demigodmode/OneSearch/issues) for bugs or concrete feature requests.
