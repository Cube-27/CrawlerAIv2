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

pnpm --dir "$root/frontend" install --frozen-lockfile --prefer-offline --reporter=silent

backend="$root/backend"
CRAWLERAI_ROLE=api start api uv --directory "$backend" run uvicorn --factory crawlerai.api.app:create_app --reload \
  --port 8000
CRAWLERAI_ROLE=worker start worker uv --directory "$backend" run crawlerai worker
CRAWLERAI_ROLE=scheduler start scheduler uv --directory "$backend" run crawlerai scheduler
start web pnpm --dir "$root/frontend" dev

echo "[dev-up] app: http://localhost:5173 (API http://localhost:8000). Ctrl+C stops everything."
# Returns when the first process exits; the EXIT trap then stops the rest.
wait -n "${pids[@]}"
