#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/pm-agent-pycache}"
export PYTHONPATH="$ROOT_DIR/apps/api:$ROOT_DIR/apps/worker${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT_DIR/apps/api"

python_supports_repo() {
  local python_bin="$1"
  [[ -x "$python_bin" ]] || return 1
  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

PYTHON_BIN="$(resolve_python_bin 2>/dev/null || true)"
if [[ -n "$PYTHON_BIN" ]] && python_supports_repo "$PYTHON_BIN"; then
  exec "$PYTHON_BIN" -m uvicorn pm_agent_api.main:app --host "$API_HOST" --port "$API_PORT"
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run --project "$ROOT_DIR/apps/api" --python 3.12 -m uvicorn pm_agent_api.main:app --host "$API_HOST" --port "$API_PORT"
fi

echo "No usable Python 3.10+ runtime found for API startup." >&2
echo "Install Python 3.10+ or ensure uv is available." >&2
exit 1
