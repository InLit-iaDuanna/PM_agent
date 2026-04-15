#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

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

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_deploy.sh [--pull] [--skip-build]

Deploy the Docker stack from the repository root, wait for healthy services,
and print the local access URL.
EOF
}

ensure_docker_env_file() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    return 0
  fi

  if [[ -f "$ROOT_DIR/.env.docker.example" ]]; then
    cp "$ROOT_DIR/.env.docker.example" "$ROOT_DIR/.env"
    echo "Created .env from .env.docker.example"
    echo "Edit .env before public deployment, especially MINIMAX_API_KEY and registration settings."
    return 0
  fi

  _print_error "Missing .env and .env.docker.example."
  return 1
}

PULL_IMAGES=0
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull)
      PULL_IMAGES=1
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
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
load_env_defaults "$ROOT_DIR/.env"
prepare_build_metadata_env
prepare_docker_runtime_env_file "$ROOT_DIR/.env"

if [[ "$PULL_IMAGES" == "1" ]]; then
  docker_compose pull
fi

if [[ "$SKIP_BUILD" == "1" ]]; then
  docker_compose up -d
else
  docker_compose up -d --build
fi

for service_name in api web gateway; do
  wait_for_docker_service_health "$service_name" 180
done

PUBLIC_PORT="$(resolve_gateway_public_port)"
PUBLIC_BIND_HOST="${PM_AGENT_PUBLIC_BIND_HOST:-127.0.0.1}"
if [[ "$PUBLIC_PORT" == "80" ]]; then
  LOCAL_URL="http://127.0.0.1/"
else
  LOCAL_URL="http://127.0.0.1:${PUBLIC_PORT}/"
fi

echo "Docker stack is healthy."
echo "  Local URL: $LOCAL_URL"
echo "  Gateway bind: ${PUBLIC_BIND_HOST}:${PUBLIC_PORT} -> 80"
if is_loopback_bind_host "$PUBLIC_BIND_HOST"; then
  echo "  Exposure: loopback-only (safe default)"
elif is_wildcard_bind_host "$PUBLIC_BIND_HOST"; then
  echo "  Exposure: all interfaces; restrict firewall/security-group access to trusted sources"
else
  echo "  Exposure: specific edge IP ${PUBLIC_BIND_HOST}; keep upstream access restricted"
fi
echo "  Status: docker compose ps"
echo "  Logs: docker compose logs -f gateway web api worker"
echo "  Backup: ./scripts/docker_backup_state.sh"
echo "  First admin bootstrap: open /login and register the first account"
