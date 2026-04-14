#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_restore_state.sh <archive_path> [--volume-name NAME] [--yes] [--skip-start]

Restore a PM Agent backup archive into Docker volumes.
Without --volume-name, the script restores the compose-managed flagship stack volumes.
EOF
}

ARCHIVE_PATH=""
VOLUME_NAME=""
CONFIRMED=0
SKIP_START=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volume-name)
      VOLUME_NAME="${2:-}"
      shift 2
      ;;
    --yes)
      CONFIRMED=1
      shift
      ;;
    --skip-start)
      SKIP_START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -n "$ARCHIVE_PATH" ]]; then
        _print_error "Unexpected extra argument: $1"
        usage >&2
        exit 1
      fi
      ARCHIVE_PATH="$1"
      shift
      ;;
  esac
done

if [[ -z "$ARCHIVE_PATH" ]]; then
  usage >&2
  exit 1
fi

require_command docker

if [[ "$ARCHIVE_PATH" != /* ]]; then
  ARCHIVE_PATH="$(pwd)/$ARCHIVE_PATH"
fi

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  _print_error "Archive not found: $ARCHIVE_PATH"
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
tar -xzf "$ARCHIVE_PATH" -C "$WORK_DIR"

if [[ ! -d "$WORK_DIR/volumes" ]]; then
  _print_error "Archive format is not supported: missing volumes/ directory."
  exit 1
fi

declare -a RESTORE_KEYS=()
if [[ -n "$VOLUME_NAME" ]]; then
  RESTORE_KEYS+=("$VOLUME_NAME")
else
  while IFS= read -r logical_key; do
    [[ -n "$logical_key" ]] || continue
    RESTORE_KEYS+=("$logical_key")
  done < <(compose_managed_volume_keys)
fi

if [[ "$CONFIRMED" != "1" ]]; then
  echo "This will overwrite the following Docker volume targets:"
  for logical_key in "${RESTORE_KEYS[@]}"; do
    if [[ -n "$VOLUME_NAME" ]]; then
      echo "  $logical_key"
    else
      echo "  $(resolve_compose_state_volume_name "$logical_key")"
    fi
  done
  echo "From archive: $ARCHIVE_PATH"
  read -r -p "Continue? [y/N] " confirmation
  if [[ ! "$confirmation" =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 1
  fi
fi

if [[ -z "$VOLUME_NAME" ]]; then
  docker_compose down
fi

for logical_key in "${RESTORE_KEYS[@]}"; do
  target_volume="$logical_key"
  archive_label="$logical_key"
  if [[ -z "$VOLUME_NAME" ]]; then
    target_volume="$(resolve_compose_state_volume_name "$logical_key")"
    archive_label="$logical_key"
  fi

  archive_member="$WORK_DIR/volumes/${archive_label}.tar.gz"
  if [[ ! -f "$archive_member" ]]; then
    _print_error "Archive does not include volume payload: ${archive_label}.tar.gz"
    exit 1
  fi

  if ! docker volume inspect "$target_volume" >/dev/null 2>&1; then
    docker volume create "$target_volume" >/dev/null
  fi

  docker run --rm \
    -v "${target_volume}:/target" \
    -v "${WORK_DIR}/volumes:/backup:ro" \
    alpine:3.20 \
    sh -lc "mkdir -p /target && find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar -xzf /backup/${archive_label}.tar.gz -C /target"
done

echo "Restore completed."
echo "  Archive: $ARCHIVE_PATH"

if [[ -z "$VOLUME_NAME" && "$SKIP_START" != "1" ]]; then
  docker_compose up -d
  for service_name in postgres redis object-storage api worker web gateway caddy; do
    if compose_has_service "$service_name"; then
      wait_for_docker_service_health "$service_name" 240
    fi
  done
  echo "  Stack restarted."
fi
