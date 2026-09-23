#!/usr/bin/env bash
# Free POS (:8000) and Payments (:8080) before restarting with run-pos.sh / run-payments.sh.
set -euo pipefail
for port in 8000 8001 8080; do
  if fuser "${port}/tcp" >/dev/null 2>&1; then
    echo "Stopping process on port ${port}..."
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
done
sleep 0.5
if ss -tln 2>/dev/null | grep -qE ':8000|:8001|:8080'; then
  echo "Warning: 8000, 8001, or 8080 still in use — check with: ss -tlnp | grep -E ':8000|:8080'"
  exit 1
fi
echo "Dev server ports are free (8000 POS, 8080 Payments)."
