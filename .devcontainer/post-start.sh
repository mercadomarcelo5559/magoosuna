#!/usr/bin/env bash
# Se ejecuta CADA VEZ que se arranca el Codespace (también tras reanudarlo).
set -uo pipefail

cd "${CODESPACE_VSCODE_FOLDER:-$PWD}"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if grep -q "postgresql" .env 2>/dev/null; then
    echo "→ Reanudando PostgreSQL y Redis…"
    docker compose up -d postgres redis >/dev/null 2>&1 || true
  fi
fi

cat <<'MSG'

  Social Video API — entorno listo.

    make dev       arranca la API con recarga automática (Swagger en /docs)
    make worker    arranca el worker de publicaciones (Celery)
    make test      ejecuta los tests
    make help      todos los comandos

  Recuerda: un Codespace DETENIDO no publica nada. Para publicaciones
  programadas 24/7 hace falta un servidor permanente (README → Producción).

MSG
