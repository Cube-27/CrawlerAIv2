# Local development (SPEC-00 §4.4). Needs Docker, uv and GNU make.

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
export

# `check-sdk` is not part of `check`: it needs `uvx` and the SDK's own `pnpm install`. CI checks only that the SDKs
# were generated from the current API document (tools/tests/test_sdk_digest.py).
.PHONY: sdk check-sdk dev up db db-down migrate api api-client check check-data check-tools check-backend \
	check-frontend check-api-client check-licenses check-size-gates check-complexity check-theme

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

migrate:
	cd backend && uv run alembic upgrade head
	cd backend && uv run crawlerai schemas sync

api:
	cd backend && CRAWLERAI_ROLE=api uv run uvicorn --factory crawlerai.api.app:create_app --reload --port 8000

## Regenerate frontend/openapi.json and the TS client types from the backend (SPEC-00 §4.5). CI fails when the
## committed files differ from a fresh run.
api-client:
	cd backend && $(UV_RUN) crawlerai openapi > ../frontend/openapi.json
	cd frontend && pnpm gen:api

## Everything CI runs (SPEC-00 §4.4, §4.6), in the same order per job, failing at the first error. Needs Docker for
## the backend's database steps and `pnpm install` in frontend/. The fast staged-file hooks are in
## .pre-commit-config.yaml.
check: check-data check-size-gates check-complexity check-theme check-tools check-backend check-frontend \
	check-api-client check-licenses

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

# Visual values only in frontend/src/app/theme.css, UI only from @heroui/react (openspec/conventions/DESIGN.md, Theming and Stack).
check-theme:
	cd backend && $(UV_RUN) python ../tools/theme_only_check.py

check-tools:
	cd backend && $(UV_RUN) ruff check ../tools
	cd backend && $(UV_RUN) ruff format --check ../tools
	cd backend && $(UV_RUN) mypy --strict ../tools
	cd backend && $(UV_RUN) pytest ../tools/tests
	cd backend && $(UV_RUN) python ../tools/site_literal_scan.py --public
	cd backend && $(UV_RUN) python ../tools/decision_ids.py

# Same steps and order as CI's backend job. The migration round trip and the tests (tests/db needs a live Postgres)
# run against a scratch database recreated each run, so the dev database keeps its data. 127.0.0.1, not localhost:
# asyncpg can hang resolving localhost on Windows.
CHECK_DATABASE_URL := postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai_check
CHECK_PRIVATE_DATABASE_URL := postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai_private_check

check-backend: db
	cd backend && $(UV_RUN) ruff check
	cd backend && $(UV_RUN) ruff format --check
	cd backend && $(UV_RUN) mypy src tests migrations
	cd backend && $(UV_RUN) lint-imports
	cd backend && $(UV_RUN) patchright install --no-shell chromium
	$(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -q -U postgres \
		-c 'DROP DATABASE IF EXISTS crawlerai_check' -c 'CREATE DATABASE crawlerai_check OWNER app' \
		-c 'DROP DATABASE IF EXISTS crawlerai_private_check' -c 'CREATE DATABASE crawlerai_private_check OWNER app'
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic upgrade head
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic downgrade base
	cd backend && CRAWLERAI_DATABASE_URL=$(CHECK_DATABASE_URL) $(UV_RUN) alembic upgrade head
	cd backend && CRAWLERAI_TEST_DATABASE_URL=$(CHECK_DATABASE_URL) \
		CRAWLERAI_TEST_PRIVATE_DATABASE_URL=$(CHECK_PRIVATE_DATABASE_URL) $(UV_RUN) pytest

## Regenerate the Python and TypeScript SDKs' generated files from frontend/openapi.json (run `make api-client` first).
sdk:
	sdk/python/generate.sh
	cd sdk/typescript && pnpm install --frozen-lockfile && pnpm gen
	python3 tools/sdk_digest.py

check-sdk: sdk
	git diff --exit-code -- sdk || { echo "SDK out of date: run 'make sdk' and commit the result."; exit 1; }
	cd sdk/typescript && pnpm check && pnpm test
	cd sdk/python && uv venv --clear -q .venv && uv pip install -q -e ".[dev]" && .venv/bin/ruff check src tests \
		&& .venv/bin/mypy src tests && .venv/bin/pytest -q

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
