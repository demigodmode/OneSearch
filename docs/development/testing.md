# Testing

Testing OneSearch.

!!! note "Coming Soon"
    Comprehensive testing guide coming soon.

## Backend Tests

```bash
cd backend
uv run pytest
```

## Frontend Lint/Build

```bash
cd frontend
npm run lint
npm run build
```

## Writing Tests

- Use pytest for backend tests
- Test extractors with sample files
- Test API endpoints
- Mock external dependencies (Meilisearch)

See existing tests for examples.
