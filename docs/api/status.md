# Status & Health API

Monitor OneSearch system status.

!!! note "Coming Soon"
    Detailed status API documentation coming soon.

## Endpoints

- `GET /api/health` - API health check
- `GET /api/status` - Overall indexing status
- `GET /api/status/{source_id}` - Source-specific status

## Example

```bash
curl http://localhost:8000/api/status
```

See [API Overview](index.md#quick-examples) for more examples.
