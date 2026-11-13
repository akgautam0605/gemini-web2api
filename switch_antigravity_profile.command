#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.json"
GATEWAY_URL="${GEMINI_WEB2API_URL:-http://127.0.0.1:8081}"

APP_NAME="/Applications/Antigravity.app"
APP_BIN="$APP_NAME/Contents/MacOS/Antigravity"
IDE_NAME="/Applications/Antigravity IDE.app"
IDE_BIN="$IDE_NAME/Contents/MacOS/Electron"

APP_PROFILE_DIR="/private/tmp/antigravity-gateway-profile-all"
IDE_PROFILE_DIR="/private/tmp/antigravity-ide-gateway-profile"
LOG_FILE="${HOME}/Library/Logs/gemini-web2api-profile-switcher.log"

unset AGY_LLM_GATEWAY_URL AGY_LLM_GATEWAY_API_KEY AGY_LLM_GATEWAY_WIRE_PROTOCOL AGY_LLM_GATEWAY_MODELS

read_gateway_key() {
  local key=""
  if [[ -f "$CONFIG_FILE" ]]; then
    key="$(python3 - "$CONFIG_FILE" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as config_file:
        keys = json.load(config_file).get("api_keys") or []
    if isinstance(keys, list) and keys:
        print(keys[0])
except (OSError, ValueError, AttributeError):
    pass
PY
)"
  fi

  if [[ -z "$key" ]]; then
    printf 'No gateway API key was found in config.json.\n' >&2
    read -r -s -p 'Gateway API key: ' key
    printf '\n' >&2
  fi
  if [[ -z "$key" ]]; then
    printf 'A gateway API key is required.\n' >&2
    return 1
  fi
  printf '%s' "$key"
}

read_models() {
  local key="$1"
  GATEWAY_API_KEY="$key" GATEWAY_URL="$GATEWAY_URL" python3 <<'PY'
import json
import os
import sys
import urllib.request

url = os.environ["GATEWAY_URL"].rstrip("/") + "/v1/models"
request = urllib.request.Request(
    url,
    headers={"Authorization": "Bearer " + os.environ["GATEWAY_API_KEY"]},
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        models = json.load(response).get("data", [])
    print(",".join(model["id"] for model in models if isinstance(model.get("id"), str)))
except Exception:
    print("Could not load the local gateway model list.", file=sys.stderr)
    raise SystemExit(1)
PY
}

start_gateway_if_needed() {
  local key="$1" models="" python_bin=""
  if models="$(read_models "$key" 2>/dev/null)"; then
    printf 'Local gateway is already running at %s.\n' "$GATEWAY_URL" >&2
    printf '%s' "$models"
    return 0
  fi

  if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    python_bin="$PROJECT_DIR/.venv/bin/python"
  elif [[ -x "$PROJECT_DIR/venv/bin/python" ]]; then
    python_bin="$PROJECT_DIR/venv/bin/python"
  else
    python_bin="$(command -v python3 || true)"
  fi
  if [[ -z "$python_bin" ]]; then
    printf 'Python 3 was not found.\n' >&2
    return 1
  fi

  mkdir -p "$(dirname "$LOG_FILE")"
  printf 'Starting the local gateway with %s gemini_web2api.py.\n' "$python_bin" >&2
  printf 'Gateway log: %s\n' "$LOG_FILE" >&2
  (
    cd "$PROJECT_DIR"
    nohup "$python_bin" gemini_web2api.py </dev/null >>"$LOG_FILE" 2>&1 &
  )

  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if models="$(read_models "$key" 2>/dev/null)"; then
      printf 'Local gateway is ready at %s.\n' "$GATEWAY_URL" >&2
      printf '%s' "$models"
      return 0
    fi
    sleep 1
  done

  printf 'The local gateway did not become ready. Check: %s\n' "$LOG_FILE" >&2
  return 1
}

launch_gateway_profile() {
  local surface="$1" binary="$2" profile_dir="$3"
  if [[ ! -x "$binary" ]]; then
    printf 'Could not find executable: %s\n' "$binary" >&2
    exit 1
  fi

  local gateway_key model_ids
  gateway_key="$(read_gateway_key)"
  if ! model_ids="$(start_gateway_if_needed "$gateway_key")"; then
    exit 1
  fi
  if [[ -z "$model_ids" ]]; then
    printf 'The gateway returned an empty model list.\n' >&2
    exit 1
  fi

  mkdir -p "$profile_dir"
  printf 'Launching %s with the local gateway.\n' "$surface"
  printf 'Profile: %s\n' "$profile_dir"
  printf 'Gateway: %s\n' "$GATEWAY_URL"
  exec env \
    AGY_LLM_GATEWAY_URL="$GATEWAY_URL" \
    AGY_LLM_GATEWAY_API_KEY="$gateway_key" \
    AGY_LLM_GATEWAY_WIRE_PROTOCOL='openai' \
    AGY_LLM_GATEWAY_MODELS="$model_ids" \
    "$binary" --user-data-dir="$profile_dir" --new-window
}

launch_normal_profile() {
  local surface="$1" app_path="$2"
  if [[ ! -d "$app_path" ]]; then
    printf 'Could not find app: %s\n' "$app_path" >&2
    exit 1
  fi
  printf 'Opening %s with its normal macOS profile.\n' "$surface"
  exec open -a "$app_path"
}

printf '\nAntigravity profile switcher\n'
printf '1) Antigravity App — local gateway profile\n'
printf '2) Antigravity IDE — local gateway profile\n'
printf '3) Antigravity App — normal profile\n'
printf '4) Antigravity IDE — normal profile\n'
printf 'q) Quit\n\n'
read -r -p 'Choose an option: ' choice

case "$choice" in
  1) launch_gateway_profile 'Antigravity App' "$APP_BIN" "$APP_PROFILE_DIR" ;;
  2) launch_gateway_profile 'Antigravity IDE' "$IDE_BIN" "$IDE_PROFILE_DIR" ;;
  3) launch_normal_profile 'Antigravity App' "$APP_NAME" ;;
  4) launch_normal_profile 'Antigravity IDE' "$IDE_NAME" ;;
  q|Q) exit 0 ;;
  *) printf 'Invalid option.\n' >&2; exit 2 ;;
esac
