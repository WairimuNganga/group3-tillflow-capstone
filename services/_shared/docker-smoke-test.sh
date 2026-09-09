#!/usr/bin/env bash
# Builds the golden-path image and proves, not just asserts, README.md's
# "Docker golden path" claims against the running container. Run locally, or
# via the `docker-golden-path` CI job.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
CONTAINER=tillflow-golden-path-smoke
PORT=18080

cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> building tillflow-base:ci (GIT_COMMIT_SHA=${GIT_SHA})"
docker build -f Dockerfile.base \
  --build-arg SERVICE_NAME=base \
  --build-arg GIT_COMMIT_SHA="${GIT_SHA}" \
  -t tillflow-base:ci . >/dev/null

echo "==> building tillflow-golden-path:ci"
docker build -f examples/Dockerfile \
  --build-arg BASE_IMAGE=tillflow-base:ci \
  --build-arg GIT_COMMIT_SHA="${GIT_SHA}" \
  -t tillflow-golden-path:ci . >/dev/null

echo "==> starting container (read-only rootfs, non-root enforced by image, all caps dropped, init as PID 1)"
cleanup
docker run -d --name "${CONTAINER}" --init -p "${PORT}:8080" \
  --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -e TILLFLOW_TELEMETRY_EXPORT=none \
  tillflow-golden-path:ci >/dev/null

fail() { echo "SMOKE TEST FAILED: $1" >&2; docker logs "${CONTAINER}" >&2 || true; exit 1; }

echo "==> waiting for /health"
ok=""
for _ in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 0.5
done
[ -n "${ok}" ] || fail "/health never came up"

echo "==> checking non-root uid"
uid="$(docker exec "${CONTAINER}" python -c 'import os; print(os.getuid())')"
[ "${uid}" = "10001" ] || fail "container is running as uid ${uid}, expected 10001 (non-root)"

echo "==> checking /health and /ready respond 200"
health_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/health")"
ready_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/ready")"
[ "${health_code}" = "200" ] || fail "/health returned ${health_code}, expected 200"
[ "${ready_code}" = "200" ] || fail "/ready returned ${ready_code}, expected 200"

echo "==> checking git_sha is baked into /health"
reported_sha="$(curl -s "http://127.0.0.1:${PORT}/health" | python3 -c 'import sys,json; print(json.load(sys.stdin)["git_sha"])')"
[ "${reported_sha}" = "${GIT_SHA}" ] || fail "/health reports git_sha=${reported_sha}, expected ${GIT_SHA} (ADR-009 artifact-identity contract)"

echo "==> proving read-only rootfs (a write outside /tmp must fail)"
if docker exec "${CONTAINER}" python -c "open('/app/should-fail', 'w')" >/dev/null 2>&1; then
  fail "container filesystem is writable outside /tmp — --read-only is not actually effective"
fi

echo "==> proving /tmp (tmpfs) is still writable"
docker exec "${CONTAINER}" python -c "open('/tmp/smoke-ok', 'w').write('x')" \
  || fail "/tmp is not writable even under --tmpfs /tmp — a real service needs this (e.g. Python's tempfile)"

echo "==> checking stdout is well-formed JSON with the ADR-008 required fields"
docker logs "${CONTAINER}" 2>&1 | while IFS= read -r line; do
  python3 -c "
import json, sys
line = sys.argv[1]
obj = json.loads(line)  # raises if not valid JSON — exit non-zero
for field in ('ts', 'level', 'service', 'msg'):
    assert field in obj, f'missing required field {field!r} in log line: {line}'
" "${line}" || fail "a log line is not valid ADR-008 JSON: ${line}"
done

echo "==> waiting for the image's own HEALTHCHECK to report healthy"
ok=""
for _ in $(seq 1 20); do
  status="$(docker inspect "${CONTAINER}" --format '{{.State.Health.Status}}' 2>/dev/null || echo "")"
  if [ "${status}" = "healthy" ]; then ok=1; break; fi
  sleep 1
done
[ -n "${ok}" ] || fail "container HEALTHCHECK never reached 'healthy' (last status: ${status:-unknown})"

echo "==> proving graceful shutdown (SIGTERM via --init must not hang or need SIGKILL)"
start="$(date +%s)"
docker stop -t 10 "${CONTAINER}" >/dev/null
elapsed=$(( $(date +%s) - start ))
exit_code="$(docker inspect "${CONTAINER}" --format '{{.State.ExitCode}}')"
[ "${exit_code}" = "143" ] || fail "container exited ${exit_code} on SIGTERM, expected 143 (clean SIGTERM shutdown, not a SIGKILL timeout)"
[ "${elapsed}" -lt 10 ] || fail "shutdown took ${elapsed}s and hit the 10s SIGKILL grace period — not a clean exit"

echo "==> all golden-path checks passed"
