#!/usr/bin/env bash
# Busca secretos hardcodeados en el código versionado.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "Buscando secretos hardcodeados…"
FALLOS=0

# Ficheros que NUNCA deben estar en git.
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "  ✗ El fichero .env está versionado en git. Quítalo:  git rm --cached .env"
  FALLOS=1
fi

# Patrones de credenciales reales de cada plataforma.
PATRONES=(
  'EAA[A-Za-z0-9]{40,}'                 # tokens de Meta/Facebook
  'act\.[A-Za-z0-9]{40,}'               # access tokens de TikTok
  'ya29\.[A-Za-z0-9_-]{40,}'            # access tokens de Google
  '1//[A-Za-z0-9_-]{40,}'               # refresh tokens de Google
  'AIza[A-Za-z0-9_-]{35}'               # API keys de Google
  'AKIA[A-Z0-9]{16}'                    # claves de AWS
  'sk-[A-Za-z0-9]{32,}'                 # claves tipo OpenAI
)

ARCHIVOS=$(git ls-files '*.py' '*.yml' '*.yaml' '*.json' '*.sh' '*.md' '*.toml' '*.ini' 2>/dev/null)
[ -z "$ARCHIVOS" ] && ARCHIVOS=$(find app tests scripts -type f 2>/dev/null)

for patron in "${PATRONES[@]}"; do
  # shellcheck disable=SC2086
  if RESULTADO=$(grep -InE "$patron" $ARCHIVOS 2>/dev/null); then
    echo "  ✗ Posible credencial real ($patron):"
    echo "$RESULTADO" | sed 's/^/      /'
    FALLOS=1
  fi
done

# Asignaciones sospechosas de secretos con valor literal no vacío.
SOSPECHOSAS=$(grep -InE \
  '(client_secret|app_secret|api_key|access_token|refresh_token|encryption_key|signing_secret)[[:space:]]*[:=][[:space:]]*"[^"]{12,}"' \
  $(git ls-files 'app/*.py' 'app/**/*.py' 2>/dev/null || find app -name '*.py') 2>/dev/null \
  | grep -vE '(noqa|#|""|test|dummy|ejemplo|example|PLACEHOLDER|fernet:|Bearer|OAuth )' || true)
if [ -n "$SOSPECHOSAS" ]; then
  echo "  ⚠ Revisa estas asignaciones (pueden ser literales legítimos):"
  echo "$SOSPECHOSAS" | sed 's/^/      /'
fi

if [ "$FALLOS" -eq 0 ]; then
  echo "  ✓ Sin secretos hardcodeados."
else
  echo "  ✗ Se encontraron problemas."
  exit 1
fi
