# Everest Textile Mills: one-command dev tasks.
# Fresh clone: make db-up migrate seed dev

.PHONY: install db-up db-down migrate seed dev test lint

.env:
	python3 scripts/init_env.py

frontend/node_modules: frontend/package-lock.json
	cd frontend && npm ci
	@touch frontend/node_modules

install: .env frontend/node_modules
	cd backend && uv sync

db-up: .env
	docker compose up -d --wait db

db-down:
	docker compose down

migrate: .env
	cd backend && uv run alembic upgrade head

seed: .env
	cd backend && PYTHONPATH=. uv run python ../scripts/seed.py

# api on :8000, web on :3000 (web proxies /api to api). Ctrl+C stops both.
dev: .env frontend/node_modules
	@trap 'kill 0' INT TERM; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

test: .env
	cd backend && uv run pytest

lint: .env frontend/node_modules
	cd backend && uv run ruff check . ../scripts --config pyproject.toml && uv run ruff format --check . ../scripts --config pyproject.toml
	cd frontend && npx tsc --noEmit
