# Search API

Search indexed documents via API.

!!! note "Coming Soon"
    Detailed search API documentation coming soon.

## Endpoint

```http
POST /api/search
```

## Example

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"q": "kubernetes", "limit": 10}'
```

See [API Overview](index.md#quick-examples) for more examples.

Or visit the interactive docs: http://localhost:8000/docs
