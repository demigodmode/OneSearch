# Adding File Extractors

Extractors turn files on disk into OneSearch `Document` objects. Keep them boring: check size, extract what you can, return a normalized document, and let the indexer handle the rest.

## Where extractors live

Extractor code is in:

```text
backend/app/extractors/
```

The shared base class and registry are in `backend/app/extractors/base.py`.

Existing extractors are the best examples:

- `text.py` for simple text and encoding fallback
- `markdown.py` for front matter and title detection
- `pdf.py` for partial failure handling
- `office.py` for format-specific extractors in one file

## Basic shape

`extract()` is synchronous. The base class runs it in a thread with timeout protection through `extract_with_timeout()`.

```python
from pathlib import Path

from .base import BaseExtractor, extractor_registry
from ..config import settings
from ..schemas import Document


class ExampleExtractor(BaseExtractor):
    SUPPORTED_EXTENSIONS = [".example"]
    MAX_FILE_SIZE = settings.max_text_file_size_mb * 1024 * 1024
    TIMEOUT = settings.text_extraction_timeout

    def extract(self, file_path: str) -> Document:
        self._check_file_size(file_path)

        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        doc = self._create_base_document(file_path, content)
        doc.title = path.stem
        doc.metadata = {"extraction_failed": False}
        return doc


extractor_registry.register(ExampleExtractor)
```

Most extractors should catch parse errors and return a minimal document rather than crashing the whole source. Oversized files and missing files should raise so the indexer can record the failure properly.

## Register it

Import the extractor in `backend/app/extractors/__init__.py` so registration happens when the package loads.

```python
from .example import ExampleExtractor
```

Also add it to `__all__` if the file follows the existing pattern.

## Tests to add

Put extractor tests under `backend/tests/`.

Good coverage:

- supported extension is registered
- successful extraction returns expected `type`, `content`, `title`, and metadata
- oversized files fail cleanly
- corrupt/unreadable files do not stop indexing unless that is intentional

Run a focused test while working:

```bash
cd backend
uv run pytest tests/test_example_extractor.py -v
```

Then run the broader backend suite before opening a PR:

```bash
uv run pytest
```
