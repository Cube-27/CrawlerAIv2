#!/usr/bin/env bash
# Runs the whole app locally in one terminal: the API (http://localhost:8000), a worker, the scheduler and the
# frontend dev server (http://localhost:5173), each log line prefixed with its process. Ctrl+C stops them all; so
# does any one of them exiting.
#
# Start it with `make up`: make starts Postgres, applies the migrations and exports `.env` to the processes started
# here. Needs Docker running, uv and pnpm.
set -euo pipefail

# `pwd -W` gives Git Bash on Windows a path that native tools (uv, pnpm) accept; elsewhere it fails and `pwd` is used.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && { pwd -W 2>/dev/null || pwd; })"
pids=()

# One process, its output prefixed with `[name]`. The tool itself is the background job (uv and pnpm take the
# directory as a flag, so no subshell sits in between): `$!` is its pid, and its process tree is everything it ran.
start() {
  local name=$1
  shift
  "$@" > >(sed -u "s/^/[$name] /") 2>&1 &
  pids+=("$!")
}

stop() {
  trap - INT TERM EXIT
  echo "[dev-up] stopping"
  local pid
  for pid in "${pids[@]}"; do
    if [[ -r /proc/$pid/winpid ]]; then
      # Git Bash on Windows: a POSIX signal does not reach the Python and Node processes uv and pnpm start, so end
      # the whole Windows process tree (uvicorn's reloader included). Path conversion is off so `/F` stays a flag.
      MSYS2_ARG_CONV_EXCL='*' taskkill /F /T /PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1 || true
    else
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
}
trap stop INT TERM EXIT

backend="$root/backend"

# The web UI's dev proxy acts with CRAWLERAI_UI_API_KEY. Keep the one in `.env` while the database
# holds it unrevoked; otherwise (unset, or the database was recreated) create one and write it to `.env`. Only the
# key's SHA-256 is stored, so the check hashes it the same way.
ui_key_is_live() {
  local hashed
  hashed=$(printf '%s' "$1" | sha256sum | cut -d' ' -f1)
  [[ $(docker compose -f "$root/infra/docker-compose.yml" exec -T postgres psql -U app -d crawlerai -tAc \
    "SELECT 1 FROM api_key WHERE hashed_key = '$hashed' AND revoked_at IS NULL") == 1 ]]
}

ensure_ui_key() {
  local key=${CRAWLERAI_UI_API_KEY:-} env_file="$root/.env"
  if [[ -n $key ]] && ui_key_is_live "$key"; then
    return
  fi
  key=$(uv --directory "$backend" run crawlerai apikey create --label ui | sed -n 's/.*"key": "\([^"]*\)".*/\1/p')
  [[ -n $key ]] || { echo "[dev-up] could not create a UI API key" >&2; exit 1; }
  # A key is `ck_` and base62 digits, so it needs no escaping in the sed replacement.
  if grep -q '^CRAWLERAI_UI_API_KEY=' "$env_file"; then
    sed -i "s/^CRAWLERAI_UI_API_KEY=.*/CRAWLERAI_UI_API_KEY=$key/" "$env_file"
  else
    echo "CRAWLERAI_UI_API_KEY=$key" >>"$env_file"
  fi
  # make exported the old value; Vite lets the process environment win over `.env`.
  export CRAWLERAI_UI_API_KEY=$key
  echo "[dev-up] created a UI API key and wrote it to .env"
}
ensure_ui_key

pnpm --dir "$root/frontend" install --frozen-lockfile --prefer-offline --reporter=silent
# The worker's browser rung launches Patchright's own Chromium build, pinned by the installed Patchright version; a
# new machine or a Patchright upgrade lacks it. The install does nothing when that build is already present.
uv --directory "$backend" run patchright install --no-shell chromium

start api uv --directory "$backend" run uvicorn --factory crawlerai.api.app:create_app --reload \
  --port 8000
start worker uv --directory "$backend" run crawlerai worker
start scheduler uv --directory "$backend" run crawlerai scheduler
start web pnpm --dir "$root/frontend" dev

echo "[dev-up] app: http://localhost:5173 (API http://localhost:8000). Ctrl+C stops everything."
# Returns when the first process exits; the EXIT trap then stops the rest.
wait -n "${pids[@]}"
