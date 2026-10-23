# Local development. Needs Docker, uv and GNU make.

.DEFAULT_GOAL := dev
COMPOSE := docker compose -f infra/docker-compose.yml
# CI overrides this to run against an environment it has already installed.
UV_RUN ?= uv run

.env:
	cp .env.example .env

# `.env` assignments override variables exported in the shell; command-line variables (`make dev VAR=...`) win.
-include .env
# `fs:///` then the path without its leading slash: `/home/x` and Windows' `C:/x` both give an absolute path URL.
CRAWLERAI_OBJECT_STORE := $(or $(CRAWLERAI_OBJECT_STORE),fs:///$(patsubst /%,%,$(CURDIR))/.data/objects)
CRAWLERAI_BROWSER_PROFILES := $(or $(CRAWLERAI_BROWSER_PROFILES),$(CURDIR)/.data/browser-profiles)
export

.PHONY: sdk check-sdk dev up db db-down migrate api api-client check check-data check-tools check-backend \
	check-frontend check-api-client check-licenses check-size-gates check-complexity check-theme verify-worker-queue

## Start Postgres, apply migrations and run the API on http://localhost:8000.
dev: db migrate api

## The whole app in one terminal: Postgres and migrations, then the API, a worker, the scheduler and the frontend
## on http://localhost:5173 (tools/dev_up.sh). Ctrl+C stops them all.
up: db migrate
	bash tools/dev_up.sh

db:
	$(COMPOSE) up -d --wait

db-down:
	$(COMPOSE) down

# A model change edits the one baseline migration (greenfield, no migration chain), so a local database created from
# an older baseline is already "at head" but lacks the new columns. `alembic check` compares it with the models; on
# any difference the local database is recreated from the current baseline (its data is dropped).
migrate:
	cd backend && uv run alembic upgrade head
	@if ! (cd backend && uv run alembic check >/dev/null 2>&1); then \
		echo "[migrate] the local database predates the baseline migration; recreating it (local data is dropped)"; \
		$(COMPOSE) exec -T postgres psql -U postgres -d postgres -q \
			-c "DROP DATABASE crawlerai WITH (FORCE)" -c "CREATE DATABASE crawlerai OWNER app"; \
		cd backend && uv run alembic upgrade head; \
	fi
	cd backend && uv run crawlerai schemas sync

api:
	cd backend && uv run uvicorn --factory crawlerai.api.app:create_app --reload --port 8000

## Regenerate frontend/openapi.json and the TS client types from the backend. CI fails when the
## committed files differ from a fresh run.
api-client:
	cd backend && $(UV_RUN) crawlerai openapi > ../frontend/openapi.json
	cd frontend && pnpm gen:api

## Model-check the worker/queue concurrency with TLC (.claude/skills/verify-worker-queue/SKILL.md): the checks, the
## known findings, and each broken variant caught.
verify-worker-queue:
	python3 tools/verify/worker_queue.py

## Everything CI runs, in the same order per job, failing at the first error. Needs Docker for
## the backend's database steps and `pnpm install` in frontend/. The fast staged-file hooks are in
## .pre-commit-config.yaml.
check: check-data check-size-gates check-complexity check-theme check-tools check-backend check-frontend \
	check-api-client check-sdk check-licenses

check-data:
	cd backend && $(UV_RUN) python ../tools/data_manifest_check.py

# C11: no gate beyond the two allowed; files over 800 lines only warn.
check-size-gates:
	cd backend && $(UV_RUN) python ../tools/no_size_gates.py
	cd backend && $(UV_RUN) python ../tools/file_length.py

# C11: cognitive complexity of at most 15 per function in the backend and tools/ ([tool.complexipy] in
# backend/pyproject.toml). The frontend's limit runs in `pnpm check` (check-frontend).
check-complexity:
	cd backend && $(UV_RUN) complexipy --no-ignore

# Visual values only in frontend/src/app/theme.css, UI only from @heroui/react (docs/rules.md).
check-theme:
	cd backend && $(UV_RUN) python ../tools/theme_only_check.py

check-tools:
	cd backend && $(UV_RUN) ruff check ../tools
	cd backend && $(UV_RUN) ruff format --check ../tools
	cd backend && $(UV_RUN) mypy --strict ../tools
	cd backend && $(UV_RUN) pytest ../tools/tests
	cd backend && $(UV_RUN) python ../tools/site_literal_scan.py --public

# Same steps and order as CI's backend-static and backend jobs. The migration round trip and the tests (tests/db needs a
# live Postgres) run against scratch databases recreated each run, so the dev database keeps its data: the tests run in
# parallel (`-n auto`), each xdist worker in its own copy of the migrated `crawlerai_check` (`crawlerai_check_gw0`, ...,
# `PYTEST_XDIST_AUTO_NUM_WORKERS`, else one per CPU: at least as many as `-n auto` starts). `browser` tests are skipped
# where Google Chrome is not installed (`uv run patchright install chrome` once). 127.0.0.1, not localhost: asyncpg can
# hang resolving localhost on Windows.
CHECK_DATABASE_URL := postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai_check
CHECK_PSQL = $(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -q -U postgres

check-backend: db
	cd backend && $(UV_RUN) ruff check
	cd backend && $(UV_RUN) ruff format --check
	cd backend && $(UV_RUN) mypy src tests migrations
	cd backend && $(UV_RUN) lint-imports
	$(CHECK_PSQL) -c 'DROP DATABASE IF EXISTS crawlerai_check' -c 'CREATE DATABASE crawlerai_check OWNER app'
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic upgrade head
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic downgrade base
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic upgrade head
	python3 -c "import os; n = int(os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS') or os.cpu_count() or 1); \
		[print(f'DROP DATABASE IF EXISTS crawlerai_check_gw{i};' \
		f' CREATE DATABASE crawlerai_check_gw{i} TEMPLATE crawlerai_check OWNER app;') for i in range(n)]" \
		| $(CHECK_PSQL)
	cd backend && CRAWLERAI_TEST_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) pytest -n auto

## Regenerate the Python and TypeScript SDKs' generated files from frontend/openapi.json (run `make api-client` first).
## `check-sdk` is CI's sdk job: the regenerated files must match the committed ones.
sdk:
	sdk/python/generate.sh
	cd sdk/typescript && pnpm install --frozen-lockfile && pnpm gen

check-sdk: sdk
	@# `git status`, not `git diff`: a committed file the generators recreate shows only as untracked.
	@test -z "$$(git status --porcelain -- sdk)" || { git status --short -- sdk; git diff -- sdk; \
		echo "SDK out of date: run 'make sdk' and commit the result."; exit 1; }
	cd sdk/typescript && pnpm check && pnpm test
	cd sdk/python && uv sync --frozen --no-build --no-binary-package crawlerai-sdk --extra dev -q \
		&& .venv/bin/ruff check src tests && .venv/bin/mypy src tests && .venv/bin/pytest -q

check-frontend:
	cd frontend && pnpm check
	cd frontend && pnpm test
	cd frontend && pnpm build

check-api-client: api-client
	git diff --exit-code -- frontend/openapi.json frontend/src/api/schema.d.ts || { \
		echo "API client out of date: run 'make api-client' and commit the result."; exit 1; }

# Writes the reports and SBOMs to license-report/ (gitignored), as CI does.
check-licenses:
	tools/license_scan.sh license-report
