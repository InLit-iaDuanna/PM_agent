#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

for pid_file in "$TMP_DIR"/*.pid; do
  [[ -f "$pid_file" ]] || continue
  pid="$(cat "$pid_file")"
  terminate_process_group_for_pid "$pid"
  rm -f "$pid_file"
done

terminate_pm_stack_processes

rm -f "$STACK_STATUS_FILE"

echo "Stopped PM Research Agent processes."
