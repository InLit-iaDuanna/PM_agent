#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

NODE_BIN="$(resolve_node_bin)"
NPM_BIN="$(resolve_npm_bin)"
export PATH="$(dirname "$NODE_BIN"):$(dirname "$NPM_BIN"):$PATH"

if [[ ! -f "$ROOT_DIR/apps/web/.next/BUILD_ID" || "${PM_AGENT_FORCE_WEB_BUILD:-0}" == "1" ]]; then
  "$ROOT_DIR/scripts/bootstrap_frontend.sh"
fi

cd "$ROOT_DIR"
export NEXT_PUBLIC_API_BASE_URL
exec "$NPM_BIN" --prefix "$ROOT_DIR/apps/web" run start -- --hostname "$WEB_HOST" --port "$WEB_PORT"
