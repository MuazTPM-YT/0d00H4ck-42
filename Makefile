# Everest Textile Mills: one-command dev tasks.
# Fresh clone: make db-up migrate seed dev

.PHONY: install db-up db-down db-reset migrate seed simulate simulate-live evaluate dev test lint

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

# 30 simulated days through the real services; needs an empty DB (make db-reset migrate first)
simulate: .env
	cd backend && PYTHONPATH=. uv run python ../scripts/simulate.py

# machine feed into the running API every few seconds (needs make dev in another terminal)
simulate-live: .env
	cd backend && PYTHONPATH=. uv run python ../scripts/simulate.py --live

# DESTRUCTIVE: drops and recreates the dev database. All local data is lost.
db-reset: .env
	docker compose exec -T db sh -c 'dropdb -U "$$POSTGRES_USER" --force "$$POSTGRES_DB" && createdb -U "$$POSTGRES_USER" "$$POSTGRES_DB"'

# detectors vs the simulator's planted problems, in a scratch DB; writes docs/ai-evaluation.md
evaluate: .env
	cd backend && PYTHONPATH=. uv run python ../scripts/evaluate_detectors.py

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
