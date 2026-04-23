# Examples & Workflows

Real-world CLI automation scripts.

## Standalone CLI setup

```bash
pipx install onesearch-cli
onesearch config set backend_url http://infra-stack:8000
onesearch login
onesearch whoami
```

## Scripted auth

```bash
export ONESEARCH_URL=http://infra-stack:8000
export ONESEARCH_TOKEN=xxxxx
onesearch search "compose" --json
```

## Docker fallback

The Docker image bundles the same CLI codebase as the standalone package for a given release version.

```bash
docker exec -it onesearch-app onesearch status
docker exec -it onesearch-app onesearch search "compose"
```

## Common workflows

- Automated reindexing with cron
- Search and process results
- Health monitoring and alerts
- Backup automation
