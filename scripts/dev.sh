#!/usr/bin/env bash
# Arranca API + worker + planificador en un solo comando (desarrollo).
# Ctrl+C para detener todo.
set -uo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && { set -a; . ./.env; set +a; }

PIDS=()
cleanup() {
  echo
  echo "Deteniendo…"
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo "Listo."
}
trap cleanup EXIT INT TERM

USA_CELERY="${CELERY_TASK_ALWAYS_EAGER:-false}"

if [ "$USA_CELERY" != "true" ]; then
  echo "→ Worker de publicaciones (Celery)…"
  python -m celery -A app.workers.celery_app worker --loglevel=info --concurrency=2 &
  PIDS+=($!)

  if [ "${SCHEDULER_IN_PROCESS:-true}" != "true" ]; then
    echo "→ Planificador (Celery beat)…"
    python -m celery -A app.workers.celery_app beat --loglevel=info \
      --schedule=/tmp/celerybeat-schedule &
    PIDS+=($!)
  fi
else
  echo "→ CELERY_TASK_ALWAYS_EAGER=true: las publicaciones corren dentro de la API."
fi

echo "→ API en http://localhost:8000  (Swagger: /docs)"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
