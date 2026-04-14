#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$ROOT_DIR/tmp"
STACK_STATUS_FILE="$TMP_DIR/stack.env"
mkdir -p "$TMP_DIR"

API_HOST="${PM_AGENT_API_HOST:-127.0.0.1}"
API_PORT="${PM_AGENT_API_PORT:-8000}"
WEB_HOST="${PM_AGENT_WEB_HOST:-127.0.0.1}"
WEB_PORT="${PM_AGENT_WEB_PORT:-3000}"
USER_DEFINED_NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-}"
WEB_URL=""
API_BASE_URL_DEFAULT=""

_print_error() {
  echo "$*" >&2
}

require_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    return 0
  fi
  _print_error "Required command not found: $command_name"
  return 1
}

load_env_defaults() {
  local env_file="${1:-$ROOT_DIR/.env}"
  local line=""
  local key=""
  local value=""

  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *=* ]] || continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    if [[ -z "$key" || -n "${!key+x}" ]]; then
      continue
    fi

    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    export "$key=$value"
  done < "$env_file"
}

prepare_build_metadata_env() {
  local commit="${PM_AGENT_BUILD_COMMIT:-}"
  local tag="${PM_AGENT_BUILD_TAG:-}"
  local branch="${PM_AGENT_BUILD_BRANCH:-}"
  local build_time="${PM_AGENT_BUILD_TIME:-}"

  if [[ -d "$ROOT_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
    if [[ -z "$commit" ]]; then
      commit="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || true)"
    fi
    if [[ -z "$tag" ]]; then
      tag="$(git -C "$ROOT_DIR" describe --tags --exact-match HEAD 2>/dev/null || true)"
    fi
    if [[ -z "$branch" ]]; then
      branch="$(git -C "$ROOT_DIR" symbolic-ref --short HEAD 2>/dev/null || true)"
      if [[ "$branch" == "HEAD" ]]; then
        branch=""
      fi
    fi
  fi

  if [[ -z "$build_time" ]]; then
    build_time="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  fi

  export PM_AGENT_BUILD_COMMIT="${commit:-unknown}"
  export PM_AGENT_BUILD_TAG="${tag:-}"
  export PM_AGENT_BUILD_BRANCH="${branch:-}"
  export PM_AGENT_BUILD_TIME="$build_time"
}

dotenv_escape_value() {
  local value="${1-}"
  value="${value//$'\r'/}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  printf '"%s"' "$value"
}

prepare_docker_runtime_env_file() {
  local env_file="${1:-$ROOT_DIR/.env}"
  local runtime_env_file="$TMP_DIR/docker/runtime.env"
  local line=""
  local key=""
  local value=""
  declare -A seen_keys=()
  local allowed_patterns=(
    'MINIMAX_*'
    'OPENCLI_COMMAND'
    'OPENAI_COMPAT_*'
    'OPENAI_API_KEY'
    'OPENAI_MODEL'
    'OPENAI_BASE_URL'
    'OPENAI_TIMEOUT_SECONDS'
    'PM_AGENT_ALLOW_PUBLIC_REGISTRATION'
    'PM_AGENT_AUTH_COOKIE_SAMESITE'
    'PM_AGENT_AUTH_COOKIE_SECURE'
    'PM_AGENT_CORS_ORIGINS'
    'PM_AGENT_CORS_ORIGIN_REGEX'
    'PM_AGENT_LLM_FAILOVER_COOLDOWN_SECONDS'
    'PM_AGENT_LLM_PROVIDER'
    'PM_AGENT_MAX_JOB_EVENTS'
    'PM_AGENT_PLANNER_LLM_TIMEOUT_SECONDS'
    'PM_AGENT_REGISTRATION_INVITE_CODE'
    'PM_AGENT_SESSION_MAX_AGE_SECONDS'
  )

  mkdir -p "$(dirname "$runtime_env_file")"

  is_allowed_runtime_env_key() {
    local candidate="$1"
    local pattern=""
    for pattern in "${allowed_patterns[@]}"; do
      if [[ "$candidate" == $pattern ]]; then
        return 0
      fi
    done
    return 1
  }

  if [[ -f "$env_file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%$'\r'}"
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      [[ "$line" == *=* ]] || continue

      key="${line%%=*}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      [[ -z "$key" ]] && continue
      if is_allowed_runtime_env_key "$key"; then
        seen_keys["$key"]=1
      fi
    done < "$env_file"
  fi

  while IFS='=' read -r key value; do
    if is_allowed_runtime_env_key "$key"; then
      seen_keys["$key"]=1
    fi
  done < <(env)

  : > "$runtime_env_file"
  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    [[ -n "${!key+x}" ]] || continue
    printf '%s=' "$key" >>"$runtime_env_file"
    dotenv_escape_value "${!key}" >>"$runtime_env_file"
    printf '\n' >>"$runtime_env_file"
  done < <(printf '%s\n' "${!seen_keys[@]}" | sort)

  export PM_AGENT_RUNTIME_ENV_FILE="$runtime_env_file"
}

timestamp_utc() {
  date -u +"%Y%m%dT%H%M%SZ"
}

docker_compose() {
  (
    cd "$ROOT_DIR"
    local compose_args=()
    local compose_file=""
    if [[ -n "${DOCKER_COMPOSE_FILES:-}" ]]; then
      for compose_file in $DOCKER_COMPOSE_FILES; do
        compose_args+=(-f "$compose_file")
      done
    fi
    docker compose "${compose_args[@]}" "$@"
  )
}

resolve_compose_state_volume_name() {
  local logical_volume_key="${1:-pm_agent_state}"
  local resolved_name=""

  resolved_name="$(docker_compose config 2>/dev/null | awk -v key="${logical_volume_key}:" '
    $1 == "volumes:" { in_volumes = 1; next }
    in_volumes && $1 == key { in_target = 1; next }
    in_target && $1 == "name:" { print $2; exit }
    in_volumes && in_target && $1 ~ /:$/ && $1 != "name:" { in_target = 0 }
    in_volumes && $0 !~ /^[[:space:]]/ { in_volumes = 0 }
  ')"

  if [[ -n "$resolved_name" ]]; then
    echo "$resolved_name"
    return 0
  fi

  echo "$logical_volume_key"
}

compose_managed_volume_keys() {
  printf '%s\n' \
    "pm_agent_state" \
    "pm_agent_postgres" \
    "pm_agent_redis" \
    "pm_agent_object_storage"

  if docker_compose config 2>/dev/null | grep -q '^[[:space:]]*caddy_data:$'; then
    printf '%s\n' "caddy_data"
  fi
  if docker_compose config 2>/dev/null | grep -q '^[[:space:]]*caddy_config:$'; then
    printf '%s\n' "caddy_config"
  fi
}

compose_has_service() {
  local service_name="$1"
  docker_compose config --services 2>/dev/null | grep -qx "$service_name"
}

wait_for_docker_service_health() {
  local service_name="$1"
  local timeout_seconds="${2:-180}"
  local container_id=""
  local status=""
  local deadline=$((SECONDS + timeout_seconds))

  while [[ "$SECONDS" -lt "$deadline" ]]; do
    container_id="$(docker_compose ps -q "$service_name" 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        return 0
      fi
    fi
    sleep 2
  done

  _print_error "Timed out waiting for Docker service '$service_name' to become healthy."
  return 1
}

resolve_gateway_public_port() {
  local port_mapping=""

  port_mapping="$(docker_compose port gateway 80 2>/dev/null | tail -n 1 || true)"
  if [[ -z "$port_mapping" ]]; then
    echo "${PM_AGENT_PUBLIC_PORT:-80}"
    return 0
  fi

  echo "$port_mapping" | awk -F: '{print $NF}'
}

refresh_runtime_urls() {
  WEB_URL="http://${WEB_HOST}:${WEB_PORT}/research/new"
  API_BASE_URL_DEFAULT="http://${API_HOST}:${API_PORT}"
  if [[ -n "$USER_DEFINED_NEXT_PUBLIC_API_BASE_URL" ]]; then
    export NEXT_PUBLIC_API_BASE_URL="$USER_DEFINED_NEXT_PUBLIC_API_BASE_URL"
    return 0
  fi
  export NEXT_PUBLIC_API_BASE_URL="$API_BASE_URL_DEFAULT"
}

_find_any_python() {
  command -v python3 || command -v python || true
}

port_in_use() {
  local host="$1"
  local port="$2"
  local python_bin=""
  python_bin="$(_find_any_python)"

  if [[ -n "$python_bin" ]]; then
    "$python_bin" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.25)
    sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
    return $?
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltn "( sport = :$port )" | grep -q ":$port"
    return $?
  fi

  return 1
}

find_free_port() {
  local host="$1"
  local start_port="$2"
  local python_bin=""
  python_bin="$(_find_any_python)"

  if [[ -n "$python_bin" ]]; then
    "$python_bin" - "$host" "$start_port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

while port < 65535:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            port += 1
            continue
        print(port)
        sys.exit(0)

sys.exit(1)
PY
    return $?
  fi

  local candidate="$start_port"
  while [[ "$candidate" -lt 65535 ]]; do
    if ! port_in_use "$host" "$candidate"; then
      echo "$candidate"
      return 0
    fi
    candidate=$((candidate + 1))
  done

  return 1
}

prepare_runtime_ports() {
  local explicit_api_port="${PM_AGENT_API_PORT:-}"
  local explicit_web_port="${PM_AGENT_WEB_PORT:-}"
  local next_port=""

  if port_in_use "$API_HOST" "$API_PORT"; then
    if [[ -n "$explicit_api_port" ]]; then
      _print_error "Configured API port ${API_PORT} is already in use."
      _print_error "Choose another one with PM_AGENT_API_PORT."
      return 1
    fi
    next_port="$(find_free_port "$API_HOST" "$((API_PORT + 1))")"
    echo "API port ${API_PORT} is in use. Falling back to ${next_port}."
    API_PORT="$next_port"
  fi

  if port_in_use "$WEB_HOST" "$WEB_PORT"; then
    if [[ -n "$explicit_web_port" ]]; then
      _print_error "Configured Web port ${WEB_PORT} is already in use."
      _print_error "Choose another one with PM_AGENT_WEB_PORT."
      return 1
    fi
    next_port="$(find_free_port "$WEB_HOST" "$((WEB_PORT + 1))")"
    echo "Web port ${WEB_PORT} is in use. Falling back to ${next_port}."
    WEB_PORT="$next_port"
  fi

  export PM_AGENT_API_PORT="$API_PORT"
  export PM_AGENT_WEB_PORT="$WEB_PORT"
  refresh_runtime_urls
}

ensure_env_file() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    return 0
  fi

  if [[ -f "$ROOT_DIR/.env.example" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    return 0
  fi

  cat >"$ROOT_DIR/.env" <<'EOF'
MINIMAX_API_KEY=
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
OPENCLI_COMMAND=
EOF
}

_dedupe_lines() {
  awk '!seen[$0]++'
}

_python_has_runtime_deps() {
  local python_bin="$1"
  "$python_bin" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

modules = ("fastapi", "uvicorn", "pydantic", "httpx", "bs4")
sys.exit(0 if all(importlib.util.find_spec(name) for name in modules) else 1)
PY
}

resolve_python_bin() {
  local candidates=()
  local candidate=""

  if [[ -n "${PM_AGENT_PYTHON:-}" ]]; then
    candidates+=("$PM_AGENT_PYTHON")
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    candidates+=("$ROOT_DIR/.venv/bin/python")
  fi
  candidate="$(command -v python3 || true)"
  if [[ -n "$candidate" ]]; then
    candidates+=("$candidate")
  fi
  candidate="$(command -v python || true)"
  if [[ -n "$candidate" ]]; then
    candidates+=("$candidate")
  fi

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    [[ -x "$candidate" ]] || continue
    if _python_has_runtime_deps "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done < <(printf '%s\n' "${candidates[@]}" | _dedupe_lines)

  _print_error "No usable Python runtime found."
  _print_error "Expected a Python with: fastapi, uvicorn, pydantic, httpx, beautifulsoup4."
  _print_error "You can point to one with PM_AGENT_PYTHON=/path/to/python."
  return 1
}

resolve_node_bin() {
  local candidates=()
  local candidate=""

  if [[ -n "${PM_AGENT_NODE:-}" ]]; then
    candidates+=("$PM_AGENT_NODE")
  fi
  candidate="$(command -v node || true)"
  if [[ -n "$candidate" ]]; then
    candidates+=("$candidate")
  fi
  if [[ -x "$ROOT_DIR/.tooling/node/bin/node" ]]; then
    candidates+=("$ROOT_DIR/.tooling/node/bin/node")
  fi

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    [[ -x "$candidate" ]] || continue
    echo "$candidate"
    return 0
  done < <(printf '%s\n' "${candidates[@]}" | _dedupe_lines)

  _print_error "No Node.js runtime found. Install Node or set PM_AGENT_NODE."
  return 1
}

resolve_npm_bin() {
  local candidates=()
  local candidate=""

  if [[ -n "${PM_AGENT_NPM:-}" ]]; then
    candidates+=("$PM_AGENT_NPM")
  fi
  candidate="$(command -v npm || true)"
  if [[ -n "$candidate" ]]; then
    candidates+=("$candidate")
  fi
  if [[ -x "$ROOT_DIR/.tooling/node/bin/npm" ]]; then
    candidates+=("$ROOT_DIR/.tooling/node/bin/npm")
  fi

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    [[ -x "$candidate" ]] || continue
    echo "$candidate"
    return 0
  done < <(printf '%s\n' "${candidates[@]}" | _dedupe_lines)

  _print_error "No npm binary found. Install npm or set PM_AGENT_NPM."
  return 1
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="${2:-40}"
  local python_bin="$3"

  "$python_bin" - "$url" "$timeout_seconds" <<'PY'
import sys
import time
import urllib.request

url = sys.argv[1]
timeout_seconds = float(sys.argv[2])
deadline = time.time() + timeout_seconds
last_error = None

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status < 500:
                sys.exit(0)
    except Exception as error:
        last_error = error
    time.sleep(1)

if last_error:
    print(f"Timed out waiting for {url}: {last_error}", file=sys.stderr)
else:
    print(f"Timed out waiting for {url}", file=sys.stderr)
sys.exit(1)
PY
}

open_url() {
  local url="$1"

  if [[ "${PM_AGENT_NO_OPEN:-0}" == "1" ]]; then
    return 0
  fi

  if [[ -n "${PM_AGENT_OPEN_COMMAND:-}" ]]; then
    bash -lc "$PM_AGENT_OPEN_COMMAND \"$url\"" >/dev/null 2>&1 || true
    return 0
  fi

  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
    return 0
  fi
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Start-Process '$url'" >/dev/null 2>&1 || true
    return 0
  fi
}

process_cwd() {
  local pid="$1"
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  readlink -f "/proc/$pid/cwd" 2>/dev/null || true
}

process_cmdline() {
  local pid="$1"
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  if [[ -r "/proc/$pid/cmdline" ]]; then
    tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true
    return 0
  fi

  ps -o cmd= -p "$pid" 2>/dev/null || true
}

process_group_id() {
  local pid="$1"
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]'
}

wait_for_process_exit() {
  local pid="$1"
  local attempts="${2:-30}"
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  while [[ "$attempts" -gt 0 ]]; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
    attempts=$((attempts - 1))
  done

  return 1
}

terminate_process_group_for_pid() {
  local pid="$1"
  local pgid=""
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" >/dev/null 2>&1 || return 0

  pgid="$(process_group_id "$pid")"
  if [[ -n "$pgid" ]]; then
    kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
  fi
  kill -TERM "$pid" >/dev/null 2>&1 || true

  if ! wait_for_process_exit "$pid" 25; then
    if [[ -n "$pgid" ]]; then
      kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    fi
    kill -KILL "$pid" >/dev/null 2>&1 || true
    wait_for_process_exit "$pid" 10 || true
  fi
}

is_pm_stack_process() {
  local pid="$1"
  local cmd=""
  local cwd=""
  pid="$(printf '%s' "$pid" | tr -d '[:space:]')"

  [[ -d "/proc/$pid" ]] || return 1

  cmd="$(process_cmdline "$pid")"
  cwd="$(process_cwd "$pid")"

  if [[ "$cmd" == *"pm_agent_api.main:app"* && "$cwd" == "$ROOT_DIR/apps/api" ]]; then
    return 0
  fi

  if [[ "$cwd" == "$ROOT_DIR/apps/web" || "$cwd" == "$ROOT_DIR" ]]; then
    if [[ "$cmd" == *"next-server"* || "$cmd" == *"next start"* || "$cmd" == *"npm run start"* ]]; then
      return 0
    fi
  fi

  return 1
}

terminate_pm_stack_processes() {
  local pid=""
  local pgid=""
  local matched_groups=""

  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    is_pm_stack_process "$pid" || continue
    pgid="$(process_group_id "$pid")"
    if [[ -n "$pgid" ]]; then
      if [[ " $matched_groups " == *" $pgid "* ]]; then
        continue
      fi
      matched_groups="$matched_groups $pgid"
    fi
    terminate_process_group_for_pid "$pid"
  done < <(ps -eo pid= 2>/dev/null)
}

current_web_build_id() {
  if [[ -f "$ROOT_DIR/apps/web/.next/BUILD_ID" ]]; then
    cat "$ROOT_DIR/apps/web/.next/BUILD_ID"
    return 0
  fi

  return 1
}

write_stack_status() {
  local build_id=""
  build_id="$(current_web_build_id 2>/dev/null || true)"
  cat >"$STACK_STATUS_FILE" <<EOF
PM_AGENT_API_HOST=$API_HOST
PM_AGENT_API_PORT=$API_PORT
PM_AGENT_WEB_HOST=$WEB_HOST
PM_AGENT_WEB_PORT=$WEB_PORT
PM_AGENT_API_BASE_URL=$API_BASE_URL_DEFAULT
PM_AGENT_WEB_URL=$WEB_URL
PM_AGENT_WEB_BUILD_ID=$build_id
EOF
}

warn_if_missing_minimax_key() {
  local env_file="$ROOT_DIR/.env"
  local current_key=""
  local minimax_key_name="MINIMAX_API_KEY"
  current_key="$(awk -F= -v key="$minimax_key_name" '$1 == key { line = $0; sub(/^[^=]*=/, "", line); print line; exit }' "$env_file" 2>/dev/null || true)"
  if [[ -z "$current_key" ]]; then
    echo "MINIMAX_API_KEY is empty. The app will start in deterministic fallback mode."
  fi
}

refresh_runtime_urls
