#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-onesearch:podman-smoke}"
CONTAINER_NAME="${CONTAINER_NAME:-onesearch-podman-smoke}"
PORT="${PORT:-18080}"
ROOT="${ROOT:-/tmp/onesearch-podman-smoke}"
USERNAME="${USERNAME:-podmanadmin}"
PASSWORD="${PASSWORD:-PodmanSmoke123!}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  podman unshare rm -rf "$ROOT" >/dev/null 2>&1 || rm -rf "$ROOT" >/dev/null 2>&1 || true
}

wait_health() {
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" > "$ROOT-health.json"; then
      grep -q '"status":"available"' "$ROOT-health.json" || fail "Meilisearch unavailable in health response"
      return 0
    fi
    sleep 1
  done
  fail "health did not become ready on port $PORT"
}

command -v podman >/dev/null 2>&1 || fail "podman is not installed"

cleanup
mkdir -p "$ROOT/data" "$ROOT/meili" "$ROOT/source"
echo "podman smoke searchable text" > "$ROOT/source/test.txt"

mount_label=""
if command -v getenforce >/dev/null 2>&1; then
  selinux_status="$(getenforce 2>/dev/null || true)"
  if [ "$selinux_status" = "Enforcing" ] || [ "$selinux_status" = "Permissive" ]; then
    mount_label=",Z"
  fi
fi

data_mount="$ROOT/data:/app/data"
meili_mount="$ROOT/meili:/app/meili_data"
source_mount="$ROOT/source:/data/smoke:ro"
if [ -n "$mount_label" ]; then
  data_mount="${data_mount}:Z"
  meili_mount="${meili_mount}:Z"
  source_mount="${source_mount}${mount_label}"
fi

log "Building $IMAGE_TAG with Podman"
podman build -t "$IMAGE_TAG" .

log "Starting $CONTAINER_NAME on port $PORT"
podman run -d --name "$CONTAINER_NAME" \
  -p "$PORT:8000" \
  -e ONESEARCH_MANAGED_MEILI=true \
  -e MEILI_MASTER_KEY=podman-smoke-master-key \
  -e SESSION_SECRET=podman-smoke-session-secret-123456 \
  -e DATABASE_URL=sqlite:////app/data/onesearch.db \
  -v "$data_mount" \
  -v "$meili_mount" \
  -v "$source_mount" \
  "$IMAGE_TAG" >/dev/null

wait_health

log "Running API smoke"
python3 - <<PY
import json
import time
import urllib.request

BASE = 'http://127.0.0.1:$PORT'
USERNAME = '$USERNAME'
PASSWORD = '$PASSWORD'

def request(method, path, payload=None, token=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(req, timeout=120) as response:
        body = response.read().decode('utf-8')
        return json.loads(body) if body else None

auth = request('POST', '/api/auth/setup', {'username': USERNAME, 'password': PASSWORD})
token = auth['access_token']
path_test = request('POST', '/api/sources/test-path', {'root_path': '/data/smoke'}, token=token)
if not path_test['ok']:
    raise SystemExit(f'path test failed: {path_test}')
request('POST', '/api/sources', {
    'id': 'podman-smoke',
    'name': 'Podman Smoke',
    'root_path': '/data/smoke',
    'include_patterns': ['**/*'],
    'exclude_patterns': [],
}, token=token)
reindex = request('POST', '/api/sources/podman-smoke/reindex?full=true', token=token)
if reindex['stats']['successful'] < 1:
    raise SystemExit(f'expected indexed file, got {reindex}')
for _ in range(30):
    result = request('POST', '/api/search', {'q': 'podman smoke searchable text', 'limit': 10}, token=token)
    if result['total'] >= 1:
        break
    time.sleep(1)
else:
    raise SystemExit(f'podman search failed: {result}')
print('Podman API smoke passed')
PY

if podman logs "$CONTAINER_NAME" 2>&1 | grep -q 'ERROR'; then
  podman logs "$CONTAINER_NAME" >&2
  fail "unexpected ERROR in podman logs"
fi

cleanup
log "Podman smoke passed"
