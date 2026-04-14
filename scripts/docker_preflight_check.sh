#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_preflight_check.sh [--prod]

Validate required Docker deployment inputs before starting the stack.
EOF
}

ensure_docker_env_file() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    return 0
  fi

  if [[ -f "$ROOT_DIR/.env.docker.example" ]]; then
    cp "$ROOT_DIR/.env.docker.example" "$ROOT_DIR/.env"
    echo "Created .env from .env.docker.example"
    return 0
  fi

  _print_error "Missing .env and .env.docker.example."
  return 1
}

MODE="default"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)
      MODE="prod"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      _print_error "Unknown option: $1"
      usage >&2
      exit 1
      ;;
  esac
done

require_command docker
ensure_docker_env_file

if [[ "$MODE" == "prod" ]]; then
  export DOCKER_COMPOSE_FILES="docker-compose.prod.yml"
fi

load_env_defaults "$ROOT_DIR/.env"

docker_compose config >/dev/null

if [[ -z "${MINIMAX_API_KEY:-}" ]]; then
  echo "Warning: MINIMAX_API_KEY is empty. The deployed site will fall back to deterministic behavior."
fi

if [[ "$MODE" == "prod" ]]; then
  SITE_ADDRESS="${PM_AGENT_SITE_ADDRESS:-}"
  HTTP_PORT="${PM_AGENT_HTTP_PORT:-80}"
  HTTPS_PORT="${PM_AGENT_HTTPS_PORT:-443}"
  API_BASE_URL="${PM_AGENT_NEXT_PUBLIC_API_BASE_URL:-same-origin}"

  if [[ -z "$SITE_ADDRESS" ]]; then
    _print_error "PM_AGENT_SITE_ADDRESS is required for production compose."
    exit 1
  fi
  if [[ "$SITE_ADDRESS" == "research.example.com" || "$SITE_ADDRESS" == *"example.com"* ]]; then
    _print_error "PM_AGENT_SITE_ADDRESS still looks like a placeholder: $SITE_ADDRESS"
    exit 1
  fi
  if [[ "$API_BASE_URL" != "same-origin" ]]; then
    _print_error "Production compose expects PM_AGENT_NEXT_PUBLIC_API_BASE_URL=same-origin."
    exit 1
  fi
  if [[ "${PM_AGENT_STORAGE_BACKEND:-flagship}" != "flagship" ]]; then
    _print_error "Production compose expects PM_AGENT_STORAGE_BACKEND=flagship."
    exit 1
  fi
  if [[ "${PM_AGENT_BACKGROUND_MODE:-worker}" != "worker" ]]; then
    _print_error "Production compose expects PM_AGENT_BACKGROUND_MODE=worker."
    exit 1
  fi
  if [[ "${PM_AGENT_ALLOW_PUBLIC_REGISTRATION:-false}" =~ ^(1|true|yes|on)$ ]]; then
    echo "Warning: PM_AGENT_ALLOW_PUBLIC_REGISTRATION is enabled. Public internet deploys usually want this set to false."
  fi

  if [[ "$SITE_ADDRESS" == :* || "$SITE_ADDRESS" == localhost* || "$SITE_ADDRESS" == 127.0.0.1* ]]; then
    echo "Warning: PM_AGENT_SITE_ADDRESS=$SITE_ADDRESS will run the production stack in local/plain-HTTP validation mode."
  else
    echo "Production TLS target: $SITE_ADDRESS"
  fi

  if port_in_use "127.0.0.1" "$HTTP_PORT"; then
    echo "Warning: host port $HTTP_PORT is already in use."
  fi
  if port_in_use "127.0.0.1" "$HTTPS_PORT"; then
    echo "Warning: host port $HTTPS_PORT is already in use."
  fi
fi

echo "Docker preflight check passed for mode: $MODE"
