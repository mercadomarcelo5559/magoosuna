#!/usr/bin/env bash
# ===========================================================================
#  Instalación de la Social Video API en un VPS Ubuntu/Debian recién creado.
#
#  Uso (como root, en el servidor):
#     curl -fsSL https://raw.githubusercontent.com/mercadomarcelo5559/magoosuna/main/deploy/install.sh | bash -s -- api.tudominio.com tu@correo.com
#
#  O bien, si ya clonaste el repositorio:
#     sudo bash deploy/install.sh api.tudominio.com tu@correo.com
#
#  Deja funcionando: Docker, la API con HTTPS, PostgreSQL, copias de
#  seguridad diarias, cortafuegos y arranque automático al reiniciar.
# ===========================================================================
set -euo pipefail

DOMINIO="${1:-}"
EMAIL="${2:-}"
REPO="${REPO_URL:-https://github.com/mercadomarcelo5559/magoosuna.git}"
RAMA="${REPO_BRANCH:-main}"
USUARIO="svapi"
DESTINO="/opt/social-video-api"

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m→ %s\033[0m\n' "$*"; }

if [ -z "$DOMINIO" ]; then
  rojo "Falta el dominio."
  echo "Uso: bash install.sh api.tudominio.com [tu@correo.com]"
  echo
  echo "Antes de ejecutarlo, crea un registro DNS de tipo A:"
  echo "    api.tudominio.com  →  $(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '<IP de este servidor>')"
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  rojo "Ejecútalo como root o con sudo."
  exit 1
fi

echo
verde "═══════════════════════════════════════════════════════════"
verde "  Social Video API — instalación en $DOMINIO"
verde "═══════════════════════════════════════════════════════════"
echo

# --------------------------------------------------------------- 1. Sistema
info "Actualizando el sistema e instalando utilidades…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git ufw ca-certificates openssl >/dev/null

# --------------------------------------------------------------- 2. Docker
if ! command -v docker >/dev/null 2>&1; then
  info "Instalando Docker…"
  curl -fsSL https://get.docker.com | sh >/dev/null
else
  info "Docker ya está instalado."
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ------------------------------------------------------------ 3. Cortafuegos
info "Configurando el cortafuegos (sólo SSH, HTTP y HTTPS)…"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
# PostgreSQL NO se expone: vive en la red interna de Docker.

# --------------------------------------------------------------- 4. Usuario
if ! id "$USUARIO" >/dev/null 2>&1; then
  info "Creando el usuario de servicio '$USUARIO'…"
  adduser --system --group --home "$DESTINO" --shell /bin/bash "$USUARIO" >/dev/null
fi
usermod -aG docker "$USUARIO" 2>/dev/null || true

# ------------------------------------------------------------- 5. Código
if [ -d "$DESTINO/.git" ]; then
  info "Actualizando el código…"
  git -C "$DESTINO" fetch --quiet origin "$RAMA"
  git -C "$DESTINO" checkout --quiet "$RAMA"
  git -C "$DESTINO" reset --quiet --hard "origin/$RAMA"
else
  info "Clonando el repositorio…"
  rm -rf "$DESTINO"
  git clone --quiet --branch "$RAMA" "$REPO" "$DESTINO"
fi
chown -R "$USUARIO:$USUARIO" "$DESTINO"
cd "$DESTINO"

# ----------------------------------------------------------------- 6. .env
if [ ! -f .env ]; then
  info "Generando el .env con claves nuevas…"
  cp .env.example .env

  gen_b64()  { openssl rand -base64 32 | tr '+/' '-_'; }
  gen_url()  { openssl rand -base64 36 | tr -d '\n=' | tr '+/' '-_'; }

  ENCRYPTION_KEY="$(gen_b64)"
  SIGNING_SECRET="$(gen_url)"
  ADMIN_KEY="adm_$(gen_url)"
  CLIENT_KEY="svk_$(gen_url)"
  PG_PASS="$(gen_url)"

  set_env() {
    local clave="$1" valor="$2"
    if grep -q "^${clave}=" .env; then
      python3 - "$clave" "$valor" <<'PY'
import pathlib, sys
clave, valor = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
lineas = []
for linea in p.read_text().splitlines():
    if linea.startswith(f"{clave}="):
        linea = f"{clave}={valor}"
    lineas.append(linea)
p.write_text("\n".join(lineas) + "\n")
PY
    else
      printf '%s=%s\n' "$clave" "$valor" >> .env
    fi
  }

  set_env ENVIRONMENT        production
  set_env DEBUG              false
  set_env LOG_JSON           true
  set_env PUBLIC_BASE_URL    "https://${DOMINIO}"
  set_env ENCRYPTION_KEY     "$ENCRYPTION_KEY"
  set_env SIGNING_SECRET     "$SIGNING_SECRET"
  set_env ADMIN_API_KEYS     "$ADMIN_KEY"
  set_env BOOTSTRAP_API_KEYS "$CLIENT_KEY"
  set_env CORS_ALLOW_ORIGINS "https://${DOMINIO}"
  set_env PUBLISH_MODE       solo
  set_env SCHEDULER_IN_PROCESS true
  set_env DATABASE_URL       "postgresql+psycopg://svapi:${PG_PASS}@postgres:5432/social_video_api"
  set_env INSTAGRAM_REDIRECT_URI "https://${DOMINIO}/v1/oauth/instagram/callback"
  set_env TIKTOK_REDIRECT_URI    "https://${DOMINIO}/v1/oauth/tiktok/callback"
  set_env YOUTUBE_REDIRECT_URI   "https://${DOMINIO}/v1/oauth/youtube/callback"

  {
    printf '\n# --- Despliegue (lo usa deploy/docker-compose.prod.yml) ---\n'
    printf 'DOMINIO=%s\n' "$DOMINIO"
    printf 'EMAIL_TLS=%s\n' "$EMAIL"
    printf 'POSTGRES_USER=svapi\n'
    printf 'POSTGRES_PASSWORD=%s\n' "$PG_PASS"
    printf 'POSTGRES_DB=social_video_api\n'
  } >> .env

  chmod 600 .env
  chown "$USUARIO:$USUARIO" .env
  verde "  ✓ .env creado. Tu API key de cliente:  $CLIENT_KEY"
  echo "$CLIENT_KEY" > /root/api-key-cliente.txt
  echo "$ADMIN_KEY"  > /root/api-key-admin.txt
  chmod 600 /root/api-key-cliente.txt /root/api-key-admin.txt
else
  info ".env ya existe: se conserva (no se tocan tus claves)."
  # Aseguramos que el dominio esté presente para Caddy.
  grep -q '^DOMINIO=' .env || printf 'DOMINIO=%s\n' "$DOMINIO" >> .env
fi

# ------------------------------------------------------ 7. Levantar el stack
info "Construyendo e iniciando los servicios (puede tardar unos minutos)…"
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build

# ------------------------------------------------------- 8. Copias de seguridad
info "Programando la copia de seguridad diaria…"
install -d -m 750 -o "$USUARIO" -g "$USUARIO" "$DESTINO/backups"
cat > /usr/local/bin/svapi-backup <<BACKUP
#!/usr/bin/env bash
set -euo pipefail
cd "$DESTINO"
FECHA=\$(date +%F-%H%M)
docker compose -f deploy/docker-compose.prod.yml --env-file .env exec -T postgres \\
  pg_dump -U svapi social_video_api | gzip > "$DESTINO/backups/bd-\$FECHA.sql.gz"
find "$DESTINO/backups" -name 'bd-*.sql.gz' -mtime +14 -delete
BACKUP
chmod +x /usr/local/bin/svapi-backup
cat > /etc/cron.d/svapi-backup <<CRON
# Copia de seguridad diaria de la Social Video API
0 3 * * * root /usr/local/bin/svapi-backup >> $DESTINO/backups/backup.log 2>&1
CRON

# ------------------------------------------------------ 9. Actualizador
cat > /usr/local/bin/svapi-update <<UPDATE
#!/usr/bin/env bash
set -euo pipefail
cd "$DESTINO"
/usr/local/bin/svapi-backup || true
git fetch --quiet origin "$RAMA"
git reset --quiet --hard "origin/$RAMA"
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
docker image prune -f >/dev/null
echo "Actualizado. Estado:"
curl -fsS "https://$DOMINIO/health" || curl -fsS http://localhost:8000/health
UPDATE
chmod +x /usr/local/bin/svapi-update

# --------------------------------------------------------- 10. Comprobación
info "Esperando a que la API responda…"
OK=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 "http://localhost:8000/health" >/dev/null 2>&1 \
     || docker compose -f deploy/docker-compose.prod.yml --env-file .env \
          exec -T api curl -fsS --max-time 5 http://localhost:8000/health >/dev/null 2>&1; then
    OK=1; break
  fi
  sleep 5
done

echo
if [ "$OK" -eq 1 ]; then
  verde "═══════════════════════════════════════════════════════════"
  verde "  ✓ La API está funcionando"
  verde "═══════════════════════════════════════════════════════════"
else
  rojo "La API aún no responde. Revisa los logs:"
  echo "    cd $DESTINO && docker compose -f deploy/docker-compose.prod.yml logs -f api"
fi

echo
echo "  URL:      https://$DOMINIO"
echo "  Swagger:  https://$DOMINIO/docs"
echo "  Salud:    https://$DOMINIO/health"
echo
echo "  API key de cliente (para Macaly):  /root/api-key-cliente.txt"
echo "  API key de administración:         /root/api-key-admin.txt"
echo
echo "  Registra estas Redirect URI en cada plataforma:"
echo "    https://$DOMINIO/v1/oauth/instagram/callback"
echo "    https://$DOMINIO/v1/oauth/tiktok/callback"
echo "    https://$DOMINIO/v1/oauth/youtube/callback"
echo
echo "  Comandos útiles:"
echo "    svapi-update                 actualizar a la última versión"
echo "    svapi-backup                 copia de seguridad manual"
echo "    cd $DESTINO && docker compose -f deploy/docker-compose.prod.yml logs -f api"
echo
if [ -z "$EMAIL" ]; then
  echo "  Nota: sin correo, Let's Encrypt no te avisará si un certificado falla."
  echo "        Puedes añadirlo luego en la variable EMAIL_TLS del .env."
fi
echo "  El certificado HTTPS puede tardar ~1 minuto en emitirse la primera vez."
echo
