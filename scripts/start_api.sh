#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

PYTHON_BIN="$(resolve_python_bin)"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/pm-agent-pycache}"
export PYTHONPATH="$ROOT_DIR/apps/api:$ROOT_DIR/apps/worker${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT_DIR/apps/api"
exec "$PYTHON_BIN" -m uvicorn pm_agent_api.main:app --host "$API_HOST" --port "$API_PORT"
