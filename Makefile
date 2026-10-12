# Local development (SPEC-00 §4.4). Needs Docker, uv and GNU make.

.DEFAULT_GOAL := dev
COMPOSE := docker compose -f infra/docker-compose.yml

.env:
	cp .env.example .env

# `.env` assignments override variables exported in the shell; command-line variables (`make dev VAR=...`) win.
-include .env
CRAWLERAI_OBJECT_STORE := $(or $(CRAWLERAI_OBJECT_STORE),fs://$(CURDIR)/.data/objects)
export

.PHONY: dev db db-down migrate api

## Start Postgres, apply migrations and run the API on http://localhost:8000. Later rows add the worker, the
## scheduler and the frontend here.
dev: db migrate api

db:
	$(COMPOSE) up -d --wait

db-down:
	$(COMPOSE) down

migrate:
	cd backend && uv run alembic upgrade head

api:
	cd backend && CRAWLERAI_ROLE=api uv run uvicorn --factory crawlerai.api.app:create_app --reload --port 8000
