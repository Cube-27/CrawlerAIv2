#!/bin/bash
# test_db.sh up|drop [NAME] — the one shared local Postgres for DB tests, so agents don't start a container each.
# The container is `crawlerai-test-pg` (postgres:16) on 127.0.0.1 (never localhost: asyncpg can hang resolving it on
# Windows), port $TEST_PG_PORT (default 55432, beside the dev database's 5432). NAME (default: the current worktree's
# directory name) owns one database in it, crawlerai_test_<name>.
#   up    starts the container if it is absent or stopped (a new one gets the roles and databases of
#         infra/postgres/init.sql), recreates NAME's database empty, owned by `app`, and prints the variable that
#         points tests/db at it: eval "$(tools/orchestrator/test_db.sh up)"
#   drop  drops NAME's database; the container stays for other worktrees. A no-op when it is not running.
#         cleanup_worktree.sh runs it.
# Exits 2 on bad arguments, 1 with an ERROR on stderr when Docker or Postgres fails.
set -u
usage() { echo "usage: test_db.sh up|drop [NAME]" >&2; exit 2; }
err() { echo "ERROR $*" >&2; exit 1; }
[[ $# -ge 1 && $# -le 2 ]] || usage
action=$1
case $action in up | drop) ;; *) usage ;; esac
name=${2:-$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")}
# A Postgres identifier: lower case, anything but letters and digits becomes `_` (spec-03-pr-8 -> spec_03_pr_8).
slug=$(tr '[:upper:]' '[:lower:]' <<< "$name" | tr -c 'a-z0-9\n' '_')
[[ -n $slug ]] || usage
container=crawlerai-test-pg
port=${TEST_PG_PORT:-55432}
main_db=crawlerai_test_$slug
init_sql="$(dirname "${BASH_SOURCE[0]}")/../../infra/postgres/init.sql"

running() { [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) == true ]]; }
psql_admin() {
  docker exec -i -e PGOPTIONS=-cclient_min_messages=warning "$container" psql -v ON_ERROR_STOP=1 -q -U postgres "$@"
}
drop_sql=(-c "DROP DATABASE IF EXISTS $main_db WITH (FORCE)")

# Ready on TCP: the image's first-start init runs a server on the Unix socket only, then restarts it.
wait_ready() {
  local _
  for _ in $(seq 60); do
    docker exec "$container" pg_isready -q -h 127.0.0.1 -U postgres && return 0
    sleep 1
  done
  err "$container did not accept connections within 60 s"
}

start() {
  running && return 0
  local fresh=
  if docker inspect "$container" >/dev/null 2>&1; then
    docker start "$container" >/dev/null || err "could not start $container"
  else
    docker run -d --name "$container" -e POSTGRES_PASSWORD=postgres -p "127.0.0.1:$port:5432" postgres:16 >/dev/null \
      || err "could not create $container"
    fresh=1
  fi
  wait_ready
  [[ -z $fresh ]] || psql_admin < "$init_sql" || err "could not apply infra/postgres/init.sql in $container"
}

if [[ $action == drop ]]; then
  running || exit 0
  psql_admin "${drop_sql[@]}" || err "could not drop the database of $name"
  exit 0
fi

start
psql_admin "${drop_sql[@]}" -c "CREATE DATABASE $main_db OWNER app" || err "could not create the database of $name"
echo "export CRAWLERAI_TEST_DATABASE_URL=postgresql+asyncpg://app:app@127.0.0.1:$port/$main_db"
