#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_preflight_check.sh [--prod]

Validate required Docker deployment inputs before starting the stack.
EOF
}

is_loopback_bind_host() {
  case "${1:-}" in
    127.0.0.1|localhost|::1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_wildcard_bind_host() {
  case "${1:-}" in
    0.0.0.0|::|"[::]")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

port_probe_host() {
  local bind_host="${1:-127.0.0.1}"
  if is_wildcard_bind_host "$bind_host"; then
    echo "127.0.0.1"
    return 0
  fi
  echo "$bind_host"
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

if [[ "$MODE" == "default" ]]; then
  PUBLIC_BIND_HOST="${PM_AGENT_PUBLIC_BIND_HOST:-127.0.0.1}"
  PUBLIC_PORT="${PM_AGENT_PUBLIC_PORT:-80}"

  if is_wildcard_bind_host "$PUBLIC_BIND_HOST"; then
    echo "Warning: gateway will bind ${PUBLIC_BIND_HOST}:${PUBLIC_PORT} on all interfaces."
    echo "         This can trigger cloud port-exposure alerts; prefer loopback or a private/VPC IP."
  fi

  if ! port_in_use "$(port_probe_host "$PUBLIC_BIND_HOST")" "$PUBLIC_PORT"; then
    :
  else
    echo "Warning: host port $PUBLIC_PORT is already in use on ${PUBLIC_BIND_HOST}."
  fi
fi

if [[ "$MODE" == "prod" ]]; then
  SITE_ADDRESS="${PM_AGENT_SITE_ADDRESS:-}"
  HTTP_PORT="${PM_AGENT_HTTP_PORT:-80}"
  HTTPS_PORT="${PM_AGENT_HTTPS_PORT:-443}"
  HTTP_BIND_HOST="${PM_AGENT_HTTP_BIND_HOST:-127.0.0.1}"
  HTTPS_BIND_HOST="${PM_AGENT_HTTPS_BIND_HOST:-127.0.0.1}"
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

  if is_wildcard_bind_host "$HTTP_BIND_HOST"; then
    echo "Warning: HTTP edge will bind ${HTTP_BIND_HOST}:${HTTP_PORT} on all interfaces."
    echo "         Prefer loopback or a private/VPC IP unless you intentionally want direct host exposure."
  fi
  if is_wildcard_bind_host "$HTTPS_BIND_HOST"; then
    echo "Warning: HTTPS edge will bind ${HTTPS_BIND_HOST}:${HTTPS_PORT} on all interfaces."
    echo "         Prefer a private/VPC IP behind a cloud load balancer / WAF when possible."
  fi
  if is_loopback_bind_host "$HTTP_BIND_HOST" && is_loopback_bind_host "$HTTPS_BIND_HOST" && [[ "$SITE_ADDRESS" != :* && "$SITE_ADDRESS" != localhost* && "$SITE_ADDRESS" != 127.0.0.1* ]]; then
    echo "Warning: both public edge ports are loopback-only."
    echo "         The stack will not be internet-reachable until you rebind to a private/public edge IP."
  fi

  if port_in_use "$(port_probe_host "$HTTP_BIND_HOST")" "$HTTP_PORT"; then
    echo "Warning: host port $HTTP_PORT is already in use on ${HTTP_BIND_HOST}."
  fi
  if port_in_use "$(port_probe_host "$HTTPS_BIND_HOST")" "$HTTPS_PORT"; then
    echo "Warning: host port $HTTPS_PORT is already in use on ${HTTPS_BIND_HOST}."
  fi
fi

echo "Docker preflight check passed for mode: $MODE"
