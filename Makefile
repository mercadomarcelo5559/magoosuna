# ============================================================================
#  Social Video API — atajos de desarrollo
#  Ejecuta `make help` para ver todo lo disponible.
# ============================================================================
.DEFAULT_GOAL := help
PY ?= python
SHELL := /bin/bash

.PHONY: help
help: ## Muestra esta ayuda
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- instalación
.PHONY: install
install: ## Instala las dependencias de desarrollo
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt

.PHONY: keys
keys: ## Genera claves nuevas para el .env
	@echo "ENCRYPTION_KEY=$$($(PY) -m app.security.crypto --generate-key)"
	@echo "SIGNING_SECRET=$$($(PY) -m app.security.crypto --generate-secret)"
	@echo "ADMIN_API_KEYS=adm_$$($(PY) -c 'import secrets; print(secrets.token_urlsafe(24))')"
	@echo "BOOTSTRAP_API_KEYS=$$($(PY) -m app.security.crypto --generate-api-key)"

.PHONY: env
env: ## Crea el .env a partir de .env.example (si no existe)
	@if [ -f .env ]; then echo ".env ya existe, no se toca."; \
	else cp .env.example .env && echo ".env creado. Rellena las claves con 'make keys'."; fi

# --------------------------------------------------------------- servicios
.PHONY: up
up: ## Levanta PostgreSQL y Redis con Docker
	docker compose up -d postgres redis
	@echo "Esperando a que PostgreSQL esté listo…"
	@for i in $$(seq 1 30); do \
	  docker compose exec -T postgres pg_isready -U svapi >/dev/null 2>&1 && break; sleep 2; done
	@docker compose ps

.PHONY: down
down: ## Para los contenedores (conserva los datos)
	docker compose down

.PHONY: reset
reset: ## Para los contenedores y BORRA los datos
	docker compose down -v

.PHONY: stack
stack: ## Levanta TODO con Docker (api + worker + beat + bd + redis)
	docker compose up -d --build
	@docker compose ps

.PHONY: logs
logs: ## Sigue los logs de todos los servicios Docker
	docker compose logs -f

# ------------------------------------------------------------------ desarrollo
.PHONY: dev
dev: ## Arranca la API con recarga automática (Swagger en /docs)
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: worker
worker: ## Arranca el worker de publicaciones (Celery)
	$(PY) -m celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

.PHONY: beat
beat: ## Arranca el planificador de Celery (publicaciones programadas)
	$(PY) -m celery -A app.workers.celery_app beat --loglevel=info \
	  --schedule=/tmp/celerybeat-schedule

.PHONY: all-in-one
all-in-one: ## API + worker + beat en un solo comando (desarrollo)
	@bash scripts/dev.sh

# ---------------------------------------------------------------- migraciones
.PHONY: migrate
migrate: ## Aplica las migraciones de base de datos
	$(PY) -m alembic upgrade head

.PHONY: migration
migration: ## Crea una migración nueva:  make migration m="mensaje"
	$(PY) -m alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## Revierte la última migración
	$(PY) -m alembic downgrade -1

.PHONY: db-status
db-status: ## Revisión actual de la base de datos
	$(PY) -m alembic current
	$(PY) -m alembic history

# --------------------------------------------------------------------- calidad
.PHONY: test
test: ## Ejecuta los tests
	$(PY) -m pytest -q

.PHONY: test-cov
test-cov: ## Tests con informe de cobertura
	$(PY) -m pytest --cov=app --cov-report=term-missing --cov-report=html

.PHONY: lint
lint: ## Revisa el estilo del código
	$(PY) -m ruff check .

.PHONY: format
format: ## Formatea el código
	$(PY) -m ruff format .
	$(PY) -m ruff check . --fix

.PHONY: typecheck
typecheck: ## Comprobación de tipos
	$(PY) -m mypy app

.PHONY: check
check: lint typecheck test secrets ## Todo lo que valida la CI

.PHONY: secrets
secrets: ## Busca secretos hardcodeados en el código
	@bash scripts/check_secrets.sh

# ---------------------------------------------------------------------- utils
.PHONY: health
health: ## Comprueba el estado del servicio
	@curl -s http://localhost:8000/health | $(PY) -m json.tool

.PHONY: smoke
smoke: ## Prueba de humo contra la API arrancada
	@bash scripts/smoke_test.sh

.PHONY: clean
clean: ## Borra caches y ficheros temporales
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
