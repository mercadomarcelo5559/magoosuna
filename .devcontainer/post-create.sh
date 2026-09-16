#!/usr/bin/env bash
# Se ejecuta UNA VEZ al crear el Codespace.
set -euo pipefail

echo "════════════════════════════════════════════════════════════"
echo "  Configurando el entorno de la Social Video API"
echo "════════════════════════════════════════════════════════════"

cd "${CODESPACE_VSCODE_FOLDER:-$PWD}"

echo "→ Instalando dependencias de Python…"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements-dev.txt --quiet

echo "→ Creando directorios de datos…"
mkdir -p data/media

if [ ! -f .env ]; then
  echo "→ Generando .env con claves nuevas…"
  cp .env.example .env

  ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  SIGNING_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  ADMIN_KEY="adm_$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
  CLIENT_KEY="svk_$(python -c 'import secrets; print(secrets.token_urlsafe(30))')"

  python - "$ENCRYPTION_KEY" "$SIGNING_SECRET" "$ADMIN_KEY" "$CLIENT_KEY" <<'PY'
import pathlib, sys
enc, sign, admin, client = sys.argv[1:5]
p = pathlib.Path(".env")
lines = []
for line in p.read_text().splitlines():
    if line.startswith("ENCRYPTION_KEY="):
        line = f"ENCRYPTION_KEY={enc}"
    elif line.startswith("SIGNING_SECRET="):
        line = f"SIGNING_SECRET={sign}"
    elif line.startswith("ADMIN_API_KEYS="):
        line = f"ADMIN_API_KEYS={admin}"
    elif line.startswith("BOOTSTRAP_API_KEYS="):
        line = f"BOOTSTRAP_API_KEYS={client}"
    lines.append(line)
p.write_text("\n".join(lines) + "\n")
PY
  echo "  ✓ .env creado (las claves NO se suben al repositorio)"
else
  echo "→ .env ya existe: no se toca."
fi

# Si hay Docker disponible, levantamos PostgreSQL y Redis y usamos PostgreSQL.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "→ Docker disponible: levantando PostgreSQL y Redis…"
  docker compose up -d postgres redis || true

  for _ in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U svapi >/dev/null 2>&1; then break; fi
    sleep 2
  done

  python - <<'PY'
import pathlib
p = pathlib.Path(".env")
text = p.read_text()
if "sqlite" in text:
    text = text.replace(
        "DATABASE_URL=sqlite:///./data/social_video_api.db",
        "DATABASE_URL=postgresql+psycopg://svapi:svapi@localhost:5432/social_video_api",
    )
    p.write_text(text)
    print("  ✓ DATABASE_URL apuntando a PostgreSQL")
PY

  echo "→ Aplicando migraciones…"
  set -a; . ./.env; set +a
  alembic upgrade head || echo "  ⚠ Ejecuta 'alembic upgrade head' manualmente"
else
  echo "→ Sin Docker: se usará SQLite (funciona igual para desarrollar)."
fi

if [ -n "${CODESPACE_NAME:-}" ]; then
  echo "→ Ajustando PUBLIC_BASE_URL a la URL del Codespace…"
  python - <<'PY'
import os, pathlib, re
name = os.environ["CODESPACE_NAME"]
domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
url = f"https://{name}-8000.{domain}"
p = pathlib.Path(".env")
text = p.read_text()
text = re.sub(r"^PUBLIC_BASE_URL=.*$", f"PUBLIC_BASE_URL={url}", text, flags=re.M)
for var, path in (
    ("INSTAGRAM_REDIRECT_URI", "instagram"),
    ("TIKTOK_REDIRECT_URI", "tiktok"),
    ("YOUTUBE_REDIRECT_URI", "youtube"),
):
    text = re.sub(rf"^{var}=.*$", f"{var}={url}/v1/oauth/{path}/callback", text, flags=re.M)
p.write_text(text)
print(f"  ✓ PUBLIC_BASE_URL={url}")
print("  ⚠ Registra estas Redirect URI en cada plataforma:")
for path in ("instagram", "tiktok", "youtube"):
    print(f"      {url}/v1/oauth/{path}/callback")
PY
fi

echo
echo "════════════════════════════════════════════════════════════"
echo "  Listo. Para arrancar la API:"
echo "      make dev        (o: uvicorn app.main:app --reload)"
echo "  Swagger:  \$PUBLIC_BASE_URL/docs"
echo "  Tu API key de cliente está en .env → BOOTSTRAP_API_KEYS"
echo "════════════════════════════════════════════════════════════"
