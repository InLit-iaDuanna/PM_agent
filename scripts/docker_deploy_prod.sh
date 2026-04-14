#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_deploy_prod.sh [--pull] [--skip-build] [--admin-email <email>] [--admin-password <password>] [--admin-name <name>]

Deploy the public TLS Docker stack defined by docker-compose.prod.yml.
If admin credentials are provided, the script bootstraps the first admin before starting the public Caddy entrypoint.
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

PULL_IMAGES=0
SKIP_BUILD=0
ADMIN_EMAIL="${PM_AGENT_BOOTSTRAP_ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${PM_AGENT_BOOTSTRAP_ADMIN_PASSWORD:-}"
ADMIN_NAME="${PM_AGENT_BOOTSTRAP_ADMIN_DISPLAY_NAME:-}"

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
    --admin-email)
      ADMIN_EMAIL="$2"
      shift 2
      ;;
    --admin-password)
      ADMIN_PASSWORD="$2"
      shift 2
      ;;
    --admin-name)
      ADMIN_NAME="$2"
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

export DOCKER_COMPOSE_FILES="docker-compose.prod.yml"

require_command docker
ensure_docker_env_file
"$ROOT_DIR/scripts/docker_preflight_check.sh" --prod

load_env_defaults "$ROOT_DIR/.env"
prepare_docker_runtime_env_file "$ROOT_DIR/.env"

render_caddyfile() {
  local site_address="$1"
  local template_path="$ROOT_DIR/deploy/caddy/Caddyfile.template"
  local rendered_path="$ROOT_DIR/tmp/caddy/Caddyfile"

  mkdir -p "$(dirname "$rendered_path")"
  sed "s|__PM_AGENT_SITE_ADDRESS__|$site_address|g" "$template_path" >"$rendered_path"
  export PM_AGENT_CADDYFILE_PATH="$rendered_path"
}

render_caddyfile "${PM_AGENT_SITE_ADDRESS:-}"

if [[ "$PULL_IMAGES" == "1" ]]; then
  docker_compose pull
fi

start_services() {
  if [[ "$SKIP_BUILD" == "1" ]]; then
    docker_compose up -d "$@"
  else
    docker_compose up -d --build "$@"
  fi
}

if [[ -n "$ADMIN_EMAIL" && -n "$ADMIN_PASSWORD" ]]; then
  start_services api worker web
  wait_for_docker_service_health api 180
  wait_for_docker_service_health worker 180
  wait_for_docker_service_health web 180
  bootstrap_args=(--prod --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD")
  if [[ -n "$ADMIN_NAME" ]]; then
    bootstrap_args+=(--display-name "$ADMIN_NAME")
  fi
  "$ROOT_DIR/scripts/docker_bootstrap_admin.sh" "${bootstrap_args[@]}"
  start_services caddy
else
  start_services
fi

for service_name in api worker web caddy; do
  wait_for_docker_service_health "$service_name" 180
done

docker_compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

SITE_ADDRESS="${PM_AGENT_SITE_ADDRESS:-}"
HTTP_PORT="${PM_AGENT_HTTP_PORT:-80}"
HTTPS_PORT="${PM_AGENT_HTTPS_PORT:-443}"

if [[ "$SITE_ADDRESS" == :* || "$SITE_ADDRESS" == localhost* || "$SITE_ADDRESS" == 127.0.0.1* ]]; then
  if [[ "$HTTP_PORT" == "80" ]]; then
    PUBLIC_URL="http://127.0.0.1/"
  else
    PUBLIC_URL="http://127.0.0.1:${HTTP_PORT}/"
  fi
else
  if [[ "$HTTPS_PORT" == "443" ]]; then
    PUBLIC_URL="https://${SITE_ADDRESS}/"
  else
    PUBLIC_URL="https://${SITE_ADDRESS}:${HTTPS_PORT}/"
  fi
fi

echo "Production Docker stack is healthy."
echo "  Public URL: $PUBLIC_URL"
echo "  Compose file: docker-compose.prod.yml"
echo "  Status: docker compose -f docker-compose.prod.yml ps"
echo "  Logs: docker compose -f docker-compose.prod.yml logs -f caddy web api worker"
if [[ -z "$ADMIN_EMAIL" || -z "$ADMIN_PASSWORD" ]]; then
  echo "  Bootstrap admin next: ./scripts/docker_bootstrap_admin.sh --prod --email <email> --password <password> [--display-name <name>]"
  echo "  Warning: without bootstrap credentials, the public entrypoint is already open before the first admin is created."
fi
