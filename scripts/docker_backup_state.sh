#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/docker_backup_state.sh [archive_path] [--volume-name NAME]

Backup the PM Agent Docker data volumes into a single .tar.gz archive.
If archive_path is omitted, a timestamped archive is created under ./backups.
Use --volume-name to back up a single Docker volume instead of the full flagship stack.
EOF
}

VOLUME_NAME=""
ARCHIVE_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volume-name)
      VOLUME_NAME="${2:-}"
      shift 2
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

require_command docker

if [[ -z "$ARCHIVE_PATH" ]]; then
  ARCHIVE_PATH="$ROOT_DIR/backups/pm-agent-state-$(timestamp_utc).tar.gz"
elif [[ "$ARCHIVE_PATH" != /* ]]; then
  ARCHIVE_PATH="$(pwd)/$ARCHIVE_PATH"
fi

if [[ -d "$ARCHIVE_PATH" ]]; then
  ARCHIVE_PATH="${ARCHIVE_PATH%/}/pm-agent-state-$(timestamp_utc).tar.gz"
fi

mkdir -p "$(dirname "$ARCHIVE_PATH")"

if [[ -e "$ARCHIVE_PATH" ]]; then
  _print_error "Refusing to overwrite existing archive: $ARCHIVE_PATH"
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
VOLUME_ARCHIVE_DIR="$WORK_DIR/volumes"
mkdir -p "$VOLUME_ARCHIVE_DIR"

declare -a LOGICAL_KEYS=()
if [[ -n "$VOLUME_NAME" ]]; then
  LOGICAL_KEYS+=("$VOLUME_NAME")
else
  while IFS= read -r logical_key; do
    [[ -n "$logical_key" ]] || continue
    LOGICAL_KEYS+=("$logical_key")
  done < <(compose_managed_volume_keys)
fi

MANIFEST_PATH="$WORK_DIR/manifest.txt"
: > "$MANIFEST_PATH"

for logical_key in "${LOGICAL_KEYS[@]}"; do
  resolved_name="$logical_key"
  archive_label="$logical_key"
  if [[ -z "$VOLUME_NAME" ]]; then
    resolved_name="$(resolve_compose_state_volume_name "$logical_key")"
    archive_label="$logical_key"
  fi

  docker volume inspect "$resolved_name" >/dev/null 2>&1 || {
    _print_error "Docker volume not found: $resolved_name"
    exit 1
  }

  docker run --rm \
    -v "${resolved_name}:/source:ro" \
    -v "${VOLUME_ARCHIVE_DIR}:/backup" \
    alpine:3.20 \
    sh -lc "tar -czf /backup/${archive_label}.tar.gz -C /source ."

  printf '%s=%s\n' "$archive_label" "$resolved_name" >>"$MANIFEST_PATH"
done

tar -czf "$ARCHIVE_PATH" -C "$WORK_DIR" .

echo "Backup completed."
echo "  Archive: $ARCHIVE_PATH"
if [[ -n "$VOLUME_NAME" ]]; then
  echo "  Volume: $VOLUME_NAME"
else
  echo "  Volumes:"
  while IFS= read -r line; do
    echo "    $line"
  done <"$MANIFEST_PATH"
fi
echo "  Reminder: back up .env separately; it is not stored in Docker volumes."
