# Troubleshooting

Common issues and solutions.

!!! note "Coming Soon"
    Comprehensive troubleshooting guide coming soon.

## Common Issues

### Service won't start

Check logs:
```bash
docker-compose logs -f onesearch
```

### No search results

1. Check indexing status (Admin → Status)
2. Verify source paths exist
3. Check failed files list

### Slow indexing

- Network mounts are slower
- Large PDFs take time
- Check resource limits

See [First-Time Setup](../getting-started/first-time-setup.md#troubleshooting) for more details.
