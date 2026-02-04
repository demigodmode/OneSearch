# Backend Development

Develop the OneSearch backend.

!!! note "Coming Soon"
    Comprehensive backend development guide coming soon.

## Quick Start

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

## Project Structure

```
backend/
├── app/
│   ├── api/         # API endpoints
│   ├── services/    # Business logic
│   ├── extractors/  # Document parsers
│   ├── db/          # Database models
│   ├── config.py    # Configuration
│   └── main.py      # FastAPI app
└── tests/           # Tests
```

## Running Tests

```bash
uv run pytest
```

## Adding Features

1. Update models/schemas as needed
2. Implement service logic
3. Add API endpoints
4. Write tests
5. Update documentation

See the README and local_docs/CLAUDE.md for detailed guidelines.
