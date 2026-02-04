# Backend Development

The OneSearch backend is built with FastAPI and Python 3.11+.

## Getting Started

### Prerequisites

- Python 3.11 or later
- uv (recommended) or pip
- Docker + Docker Compose (for Meilisearch)

### Initial Setup

Clone the repository and set up the backend:

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch/backend
```

Install dependencies using uv (faster than pip):

```bash
uv sync
```

This creates a `.venv` directory and installs all dependencies from `pyproject.toml`.

Or use pip if you prefer:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### Start Meilisearch

The backend needs Meilisearch running:

```bash
docker-compose up -d meilisearch
```

Set your Meilisearch master key in `.env`:

```env
MEILI_MASTER_KEY=your-key-here
```

### Run the Development Server

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or if your venv is activated:

```bash
uvicorn app.main:app --reload
```

The `--reload` flag enables auto-reload on code changes.

API docs available at http://localhost:8000/docs

---

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, startup, CORS
│   ├── config.py            # Settings from environment
│   ├── models.py            # SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── api/                 # API endpoints
│   │   ├── search.py        # POST /api/search
│   │   ├── sources.py       # CRUD for /api/sources
│   │   └── status.py        # GET /api/health, /api/status
│   ├── services/            # Business logic
│   │   ├── indexer.py       # Orchestrates indexing
│   │   ├── scanner.py       # File system walker
│   │   └── search.py        # Meilisearch wrapper
│   ├── extractors/          # Document parsers
│   │   ├── base.py          # BaseExtractor abstract class
│   │   ├── text.py          # Text files
│   │   ├── markdown.py      # Markdown
│   │   ├── pdf.py           # PDFs
│   │   └── office.py        # Office documents
│   └── db/
│       └── database.py      # SQLAlchemy setup
├── tests/                   # Tests
├── alembic/                 # Database migrations
├── pyproject.toml           # Dependencies (uv/pip)
└── uv.lock                  # Lock file (commit this!)
```

---

## Development Workflow

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Make your changes**

3. **Run tests:**
   ```bash
   uv run pytest
   ```

4. **Commit and push:**
   ```bash
   git add .
   git commit -m "add feature description"
   git push origin feature/your-feature
   ```

5. **Create a pull request**

### Adding Dependencies

Use uv to add packages:

```bash
# Regular dependency
uv add package-name

# Development dependency
uv add --dev package-name
```

This updates `pyproject.toml` and `uv.lock`. Always commit the lock file.

---

## Key Concepts

### API Endpoints

API routes live in `app/api/`. Each module handles a resource:

**search.py** - Search endpoint

**sources.py** - Source CRUD operations

**status.py** - Health checks and status

Example endpoint structure:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..schemas import SourceCreate, SourceResponse
from ..services import source_service

router = APIRouter(prefix="/api/sources", tags=["sources"])

@router.post("/", response_model=SourceResponse)
def create_source(
    source: SourceCreate,
    db: Session = Depends(get_db)
):
    return source_service.create(db, source)
```

**Key points:**
- Use Pydantic schemas for validation
- Dependency injection for database sessions
- Return proper HTTP status codes
- Handle errors with FastAPI exceptions

### Services

Business logic lives in `app/services/`. Keep API routes thin - they should just validate input and call service functions.

**indexer.py** orchestrates the indexing process:
1. Scan directories
2. Extract content
3. Send to Meilisearch
4. Update metadata

**scanner.py** walks the file system and applies glob patterns.

**search.py** wraps the Meilisearch client.

### Extractors

Extractors parse file content. All inherit from `BaseExtractor`:

```python
from abc import ABC, abstractmethod
from ..schemas import Document

class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, file_path: str) -> Document:
        pass
```

Example extractor:

```python
class TextExtractor(BaseExtractor):
    async def extract(self, file_path: str) -> Document:
        # Read file with timeout
        # Detect encoding
        # Return normalized Document
        return Document(
            path=file_path,
            content=content,
            type="text",
            # ... other fields
        )
```

**Why this pattern:**
- Easy to add new file types
- Consistent interface
- Error handling in one place
- Timeout protection built in

### Database Models

SQLAlchemy models in `app/models.py`:

```python
class Source(Base):
    __tablename__ = "sources"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False)
    # ...
```

**vs. Pydantic schemas in `app/schemas.py`:**

```python
class SourceCreate(BaseModel):
    name: str
    root_path: str
    # ...

class SourceResponse(BaseModel):
    id: str
    name: str
    # ...
```

**Why separate?**
- Models = database structure
- Schemas = API contracts
- Different concerns, different validation

### Database Migrations

OneSearch uses Alembic for migrations.

Create a migration after changing models:

```bash
uv run alembic revision --autogenerate -m "add new column"
```

Review the generated file in `alembic/versions/`. Alembic can't detect everything, so check it.

Apply migrations:

```bash
uv run alembic upgrade head
```

---

## Testing

Run all tests:

```bash
uv run pytest
```

Run specific tests:

```bash
uv run pytest tests/test_extractors.py
uv run pytest tests/test_api.py::test_search
```

Verbose output:

```bash
uv run pytest -v
```

With coverage:

```bash
uv run pytest --cov=app
```

### Writing Tests

Use pytest fixtures for setup:

```python
import pytest
from pathlib import Path

@pytest.fixture
def sample_text_file(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Sample content")
    return str(file_path)

def test_text_extractor(sample_text_file):
    extractor = TextExtractor()
    doc = await extractor.extract(sample_text_file)
    assert doc.content == "Sample content"
```

Mock external services (Meilisearch) in tests:

```python
from unittest.mock import Mock, patch

@patch('app.services.search.meilisearch_client')
def test_search(mock_client):
    mock_client.search.return_value = {"hits": []}
    # ... test code
```

---

## Common Tasks

### Adding a New Endpoint

1. Define Pydantic schemas in `schemas.py`
2. Implement route handler in `api/`
3. Add service logic in `services/`
4. Write tests
5. Update API docs if needed

### Adding a New Extractor

See [Adding File Extractors](adding-extractors.md) for a complete guide.

Quick version:
1. Create extractor class in `extractors/`
2. Inherit from `BaseExtractor`
3. Implement `extract()` method
4. Register in extractor factory
5. Add tests with sample files

### Debugging

Use FastAPI's built-in logging:

```python
import logging
logger = logging.getLogger(__name__)

logger.debug("Debug message")
logger.info("Info message")
logger.error("Error message")
```

Set `LOG_LEVEL=DEBUG` in `.env` to see all logs.

Or use Python debugger:

```python
import pdb; pdb.set_trace()
```

---

## Code Style

Follow PEP 8. Use type hints:

```python
def process_file(path: str, source_id: str) -> Document:
    # ...
```

Keep functions small and focused. Extract complex logic into helper functions.

Don't over-comment obvious code. Comment WHY, not WHAT.

---

## Performance Tips

**Async where it matters** - File I/O and network calls benefit from async. Pure Python computation doesn't.

**Batch operations** - Send documents to Meilisearch in batches, not one at a time.

**Database connections** - Use dependency injection to manage sessions properly.

**Timeouts** - Always set timeouts on external calls and file operations.

---

## Troubleshooting

### Import errors

Make sure you're in the venv:

```bash
source .venv/bin/activate  # Unix
.venv\Scripts\activate     # Windows
```

Or use uv to run directly:

```bash
uv run uvicorn ...
```

### Database migrations failing

Check current version:

```bash
uv run alembic current
```

Reset and reapply:

```bash
uv run alembic downgrade base
uv run alembic upgrade head
```

### Meilisearch connection errors

Verify Meilisearch is running:

```bash
docker-compose ps meilisearch
```

Check the master key matches in both `.env` and `docker-compose.yml`.

---

## Next Steps

- [Architecture](architecture.md) - Understand the system design
- [Frontend Development](frontend-dev.md) - Work on the web UI
- [Adding Extractors](adding-extractors.md) - Add file format support
- [Contributing](contributing.md) - Contribution guidelines
