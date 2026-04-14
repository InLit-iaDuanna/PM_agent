#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

NODE_BIN="$(resolve_node_bin)"
NPM_BIN="$(resolve_npm_bin)"
export PATH="$(dirname "$NODE_BIN"):$(dirname "$NPM_BIN"):$PATH"

cd "$ROOT_DIR"

if [[ ! -d "$ROOT_DIR/node_modules" ]]; then
  "$NPM_BIN" install
fi

if [[ "${PM_AGENT_SKIP_WEB_BUILD:-0}" != "1" ]]; then
  if ! "$NPM_BIN" --prefix "$ROOT_DIR/apps/web" run build; then
    echo "Initial web build failed. Retrying once with a clean .next directory."
    rm -rf "$ROOT_DIR/apps/web/.next"
    "$NPM_BIN" --prefix "$ROOT_DIR/apps/web" run build
  fi
fi
