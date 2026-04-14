#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

ensure_env_file
warn_if_missing_minimax_key
"$ROOT_DIR/scripts/stop_stack.sh" >/dev/null 2>&1 || true
"$ROOT_DIR/scripts/bootstrap_frontend.sh"
prepare_runtime_ports

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$ROOT_DIR/scripts/start_api.sh" >"$TMP_DIR/api.log" 2>&1 < /dev/null &
else
  nohup "$ROOT_DIR/scripts/start_api.sh" >"$TMP_DIR/api.log" 2>&1 < /dev/null &
fi
API_PID=$!
echo "$API_PID" >"$TMP_DIR/api.pid"

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$ROOT_DIR/scripts/start_web.sh" >"$TMP_DIR/web.log" 2>&1 < /dev/null &
else
  nohup "$ROOT_DIR/scripts/start_web.sh" >"$TMP_DIR/web.log" 2>&1 < /dev/null &
fi
WEB_PID=$!
echo "$WEB_PID" >"$TMP_DIR/web.pid"

PYTHON_BIN="$(resolve_python_bin)"
wait_for_http "http://${API_HOST}:${API_PORT}/" 40 "$PYTHON_BIN"
wait_for_http "http://${WEB_HOST}:${WEB_PORT}/" 60 "$PYTHON_BIN"
write_stack_status
WEB_BUILD_ID="$(current_web_build_id 2>/dev/null || true)"

echo "PM Research Agent is starting."
echo "  API: http://${API_HOST}:${API_PORT}"
echo "  Web: $WEB_URL"
if [[ -n "$WEB_BUILD_ID" ]]; then
  echo "  Web BUILD_ID: $WEB_BUILD_ID"
fi
echo "  Logs: $TMP_DIR/api.log, $TMP_DIR/web.log"

open_url "$WEB_URL"
