# CLI Installation

Install `onesearch-cli`, the standalone command-line client for a running OneSearch server.

## Recommended: pipx

```bash
pipx install onesearch-cli
```

## Fallback: install from source

```bash
cd cli
pip install -e .
```

## Connect to your server

```bash
onesearch config set backend_url http://infra-stack:8000
onesearch login
onesearch whoami
```

The CLI does not ship its own backend, indexer, or search data. It connects to the same OneSearch server used by the web UI. Tagged releases keep the Docker image and `onesearch-cli` on the same version.

## Docker fallback

If you already have the app container running, you can use the bundled CLI without installing anything locally:

```bash
docker exec -it onesearch-app onesearch status
docker exec -it onesearch-app onesearch whoami
```

See [CLI Overview](index.md) for usage.
