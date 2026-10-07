# CLI Configuration

Configure the standalone OneSearch CLI client.

## Config File

Located at:
- Linux/macOS: `~/.config/onesearch/config.yml`, or `$XDG_CONFIG_HOME/onesearch/config.yml` if that variable is set
- Windows: `%APPDATA%\onesearch\config.yml`

Example:

```yaml
backend_url: http://infra-stack:8000
auth:
  token: null
```

`onesearch config init` also writes `output` and `defaults` sections. The CLI doesn't read them yet, so changing them has no effect.

## Interactive login

```bash
onesearch config set backend_url http://infra-stack:8000
onesearch login
onesearch whoami
```

## Environment variables

Useful for scripts and CI:

```bash
export ONESEARCH_URL=http://infra-stack:8000
export ONESEARCH_TOKEN=xxxxx
onesearch search "compose" --json
```

## Docker fallback

If you prefer not to install the standalone package on a machine, you can still run the bundled CLI from the app container:

```bash
docker exec -it onesearch-app onesearch status
```

See [CLI Overview](index.md#configuration) for details.
