#!/usr/bin/env bash
# Prueba de humo contra una API ya arrancada. No publica en ninguna red social.
set -uo pipefail
cd "$(dirname "$0")/.."

BASE="${BASE_URL:-http://localhost:8000}"
[ -f .env ] && { set -a; . ./.env; set +a; }
KEY="${API_KEY:-${BOOTSTRAP_API_KEYS%%,*}}"

if [ -z "${KEY:-}" ]; then
  echo "Define API_KEY o BOOTSTRAP_API_KEYS en el .env"; exit 1
fi

OK=0; FALLO=0
check() { # check "nombre" esperado url [args...]
  local nombre="$1" esperado="$2" url="$3"; shift 3
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$@" "$BASE$url")
  if [ "$code" = "$esperado" ]; then
    echo "  ✓ $nombre ($code)"; OK=$((OK+1))
  else
    echo "  ✗ $nombre → $code (esperado $esperado)"; FALLO=$((FALLO+1))
  fi
}

AUTH=(-H "Authorization: Bearer $KEY")

echo "Prueba de humo contra $BASE"
check "salud"                     200 "/health"
check "plataformas"               200 "/v1/platforms"
check "swagger"                   200 "/docs"
check "openapi"                   200 "/openapi.json"
check "sin API key → 401"         401 "/v1/posts"
check "API key inválida → 401"    401 "/v1/posts" -H "Authorization: Bearer no_valida"
check "cuentas"                   200 "/v1/accounts" "${AUTH[@]}"
check "límites de media"          200 "/v1/media/limits" "${AUTH[@]}"
check "publicaciones"             200 "/v1/posts" "${AUTH[@]}"
check "programadas"               200 "/v1/posts/scheduled/upcoming" "${AUTH[@]}"
check "política de reintentos"    200 "/v1/posts/config/retries" "${AUTH[@]}"
check "estado de webhooks"        200 "/v1/webhooks/status" "${AUTH[@]}"
check "post inexistente → 404"    404 "/v1/posts/no-existe" "${AUTH[@]}"
check "media inexistente → 404"   404 "/v1/media/no-existe" "${AUTH[@]}"

# Subida y descarga firmada de un video real.
TMP=$(mktemp -d)
python - "$TMP/humo.mp4" <<'PY'
import sys, pathlib
pathlib.Path(sys.argv[1]).write_bytes(
    b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1" + b"\x00" * 20000
)
PY
RESP=$(curl -s "${AUTH[@]}" -F "file=@$TMP/humo.mp4;type=video/mp4" "$BASE/v1/media")
MID=$(python -c "import json,sys; print(json.loads(sys.argv[1]).get('id',''))" "$RESP" 2>/dev/null || echo "")
if [ -n "$MID" ]; then
  echo "  ✓ subida de video ($MID)"; OK=$((OK+1))
  check "detalle del video"       200 "/v1/media/$MID" "${AUTH[@]}"
  check "borrado del video"       200 "/v1/media/$MID" -X DELETE "${AUTH[@]}"
else
  echo "  ✗ subida de video: $RESP"; FALLO=$((FALLO+1))
fi
rm -rf "$TMP"

echo
echo "  $OK correctas, $FALLO fallidas"
[ "$FALLO" -eq 0 ] || exit 1
