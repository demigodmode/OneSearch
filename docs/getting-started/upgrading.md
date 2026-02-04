# Upgrading

Guide for upgrading OneSearch to newer versions.

!!! note "Coming Soon"
    Detailed upgrade instructions will be added here soon.

## Quick Upgrade

### Using Pre-built Images

```bash
# Pull latest image
docker-compose pull

# Restart services
docker-compose up -d
```

### Building from Source

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose up -d --build
```

## Version-Specific Notes

Check the [Changelog](../about/changelog.md) for breaking changes and migration notes.
