#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$ROOT_DIR/scripts/start_stack.sh"

if [[ -f "$ROOT_DIR/tmp/stack.env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/tmp/stack.env"
  echo
  echo "PM Research Agent is ready."
  echo "Web: ${PM_AGENT_WEB_URL:-unknown}"
  echo "API: ${PM_AGENT_API_BASE_URL:-unknown}"
fi
