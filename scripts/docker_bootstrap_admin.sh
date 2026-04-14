#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_bootstrap_admin.sh [--prod] --email <email> --password <password> [--display-name <name>]

Create the first admin user directly inside the running Docker API container.
EOF
}

USE_PROD_STACK=0
ADMIN_EMAIL="${PM_AGENT_BOOTSTRAP_ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${PM_AGENT_BOOTSTRAP_ADMIN_PASSWORD:-}"
ADMIN_DISPLAY_NAME="${PM_AGENT_BOOTSTRAP_ADMIN_DISPLAY_NAME:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)
      USE_PROD_STACK=1
      shift
      ;;
    --email)
      ADMIN_EMAIL="$2"
      shift 2
      ;;
    --password)
      ADMIN_PASSWORD="$2"
      shift 2
      ;;
    --display-name)
      ADMIN_DISPLAY_NAME="$2"
      shift 2
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

if [[ -z "$ADMIN_EMAIL" || -z "$ADMIN_PASSWORD" ]]; then
  _print_error "Both --email and --password are required."
  usage >&2
  exit 1
fi

if [[ "$USE_PROD_STACK" == "1" ]]; then
  export DOCKER_COMPOSE_FILES="docker-compose.prod.yml"
fi

require_command docker
wait_for_docker_service_health api 180

bootstrap_args=(exec -T api python -m pm_agent_api.bootstrap_admin --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD")
if [[ -n "$ADMIN_DISPLAY_NAME" ]]; then
  bootstrap_args+=(--display-name "$ADMIN_DISPLAY_NAME")
fi

docker_compose "${bootstrap_args[@]}"
echo "Bootstrap admin ensured: $ADMIN_EMAIL"
