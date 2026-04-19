#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

NODE_BIN="$(resolve_node_bin)"
NPM_BIN="$(resolve_npm_bin)"
export PATH="$(dirname "$NODE_BIN"):$(dirname "$NPM_BIN"):$PATH"

if [[ ! -f "$ROOT_DIR/apps/web/.next/BUILD_ID" || "${PM_AGENT_FORCE_WEB_BUILD:-0}" == "1" ]]; then
  "$ROOT_DIR/scripts/bootstrap_frontend.sh"
fi

export NEXT_PUBLIC_API_BASE_URL

STANDALONE_SERVER="$ROOT_DIR/apps/web/.next/standalone/apps/web/server.js"
STANDALONE_ROOT="$ROOT_DIR/apps/web/.next/standalone/apps/web"

if [[ -f "$STANDALONE_SERVER" ]]; then
  mkdir -p "$STANDALONE_ROOT/.next"
  rm -rf "$STANDALONE_ROOT/.next/static"
  cp -R "$ROOT_DIR/apps/web/.next/static" "$STANDALONE_ROOT/.next/static"
  if [[ -d "$ROOT_DIR/apps/web/public" ]]; then
    rm -rf "$STANDALONE_ROOT/public"
    cp -R "$ROOT_DIR/apps/web/public" "$STANDALONE_ROOT/public"
  fi
  export PORT="$WEB_PORT"
  export HOSTNAME="$WEB_HOST"
  cd "$ROOT_DIR/apps/web/.next/standalone"
  exec "$NODE_BIN" apps/web/server.js
fi

cd "$ROOT_DIR"
exec "$NPM_BIN" --prefix "$ROOT_DIR/apps/web" run start -- --hostname "$WEB_HOST" --port "$WEB_PORT"
