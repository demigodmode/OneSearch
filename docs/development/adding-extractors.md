# Adding File Extractors

Add support for new file formats.

!!! note "Coming Soon"
    Detailed extractor development guide coming soon.

## Quick Overview

1. Create new extractor class in `backend/app/extractors/`
2. Inherit from `BaseExtractor`
3. Implement `extract()` method
4. Add timeout and error handling
5. Register extractor
6. Write tests

## Example Structure

```python
from .base import BaseExtractor
from ..schemas import Document

class NewFormatExtractor(BaseExtractor):
    async def extract(self, file_path: str) -> Document:
        # Read file with timeout
        # Parse content
        # Return normalized Document
        pass
```

See existing extractors for examples.
