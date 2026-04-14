#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/server_update.sh [options]

One-click server update flow:
1) fetch code from origin
2) checkout target ref (default: main)
3) backup compose-managed Docker volumes
4) redeploy Docker stack

Options:
  --ref <ref>              Git ref to deploy (branch or tag). Default: main
  --prod                   Use docker-compose.prod.yml + docker_deploy_prod.sh
  --project-name <name>    Override COMPOSE_PROJECT_NAME for this run
  --no-backup              Skip docker volume backup before deploy
  --no-pull                Skip pulling Docker images
  --skip-build             Pass --skip-build to deploy script
  --admin-email <email>    (prod only) bootstrap admin email
  --admin-password <pass>  (prod only) bootstrap admin password
  --admin-name <name>      (prod only) bootstrap admin display name
  -h, --help               Show help
EOF
}

TARGET_REF="main"
MODE="default"
DO_BACKUP=1
PULL_IMAGES=1
SKIP_BUILD=0
OVERRIDE_PROJECT_NAME=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
ADMIN_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      TARGET_REF="$2"
      shift 2
      ;;
    --prod)
      MODE="prod"
      shift
      ;;
    --project-name)
      OVERRIDE_PROJECT_NAME="$2"
      shift 2
      ;;
    --no-backup)
      DO_BACKUP=0
      shift
      ;;
    --no-pull)
      PULL_IMAGES=0
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

if [[ -n "$OVERRIDE_PROJECT_NAME" ]]; then
  export COMPOSE_PROJECT_NAME="$OVERRIDE_PROJECT_NAME"
fi

if [[ "$MODE" != "prod" ]]; then
  if [[ -n "$ADMIN_EMAIL" || -n "$ADMIN_PASSWORD" || -n "$ADMIN_NAME" ]]; then
    _print_error "--admin-* flags are only supported with --prod."
    exit 1
  fi
fi

if [[ "$MODE" == "prod" ]]; then
  if [[ -n "$ADMIN_EMAIL" && -z "$ADMIN_PASSWORD" ]]; then
    _print_error "--admin-password is required when --admin-email is provided."
    exit 1
  fi
  if [[ -z "$ADMIN_EMAIL" && -n "$ADMIN_PASSWORD" ]]; then
    _print_error "--admin-email is required when --admin-password is provided."
    exit 1
  fi
fi

require_command git
require_command docker

cd "$ROOT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  _print_error "Working tree is not clean. Commit/stash local changes before running server_update."
  exit 1
fi

echo "Fetching latest refs from origin..."
git fetch origin --tags --prune

if git show-ref --verify --quiet "refs/remotes/origin/$TARGET_REF"; then
  echo "Deploying remote branch: origin/$TARGET_REF"
  if git show-ref --verify --quiet "refs/heads/$TARGET_REF"; then
    git checkout "$TARGET_REF"
  else
    git checkout -b "$TARGET_REF" --track "origin/$TARGET_REF"
  fi
  git pull --ff-only origin "$TARGET_REF"
elif git show-ref --verify --quiet "refs/tags/$TARGET_REF"; then
  echo "Deploying tag: $TARGET_REF"
  git checkout "$TARGET_REF"
else
  _print_error "Target ref not found on origin or local tags: $TARGET_REF"
  exit 1
fi

if [[ "$DO_BACKUP" == "1" ]]; then
  echo "Creating Docker volume backup before deploy..."
  if [[ "$MODE" == "prod" ]]; then
    DOCKER_COMPOSE_FILES="docker-compose.prod.yml" "$ROOT_DIR/scripts/docker_backup_state.sh"
  else
    "$ROOT_DIR/scripts/docker_backup_state.sh"
  fi
fi

deploy_cmd=("$ROOT_DIR/scripts/docker_deploy.sh")
if [[ "$MODE" == "prod" ]]; then
  deploy_cmd=("$ROOT_DIR/scripts/docker_deploy_prod.sh")
fi

deploy_args=()
if [[ "$PULL_IMAGES" == "1" ]]; then
  deploy_args+=(--pull)
fi
if [[ "$SKIP_BUILD" == "1" ]]; then
  deploy_args+=(--skip-build)
fi
if [[ "$MODE" == "prod" && -n "$ADMIN_EMAIL" && -n "$ADMIN_PASSWORD" ]]; then
  deploy_args+=(--admin-email "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD")
  if [[ -n "$ADMIN_NAME" ]]; then
    deploy_args+=(--admin-name "$ADMIN_NAME")
  fi
fi

echo "Running deploy script: ${deploy_cmd[*]} ${deploy_args[*]}"
"${deploy_cmd[@]}" "${deploy_args[@]}"

echo "Update completed."
echo "Active git commit: $(git rev-parse --short HEAD)"
if [[ "$MODE" == "prod" ]]; then
  echo "Check status: docker compose -f docker-compose.prod.yml ps"
  echo "Tail logs: docker compose -f docker-compose.prod.yml logs -f caddy web api worker"
else
  if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
    echo "Check status: docker compose -p ${COMPOSE_PROJECT_NAME} ps"
    echo "Tail logs: docker compose -p ${COMPOSE_PROJECT_NAME} logs -f gateway web api worker"
  else
    echo "Check status: docker compose ps"
    echo "Tail logs: docker compose logs -f gateway web api worker"
  fi
fi
