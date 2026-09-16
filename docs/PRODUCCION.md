# De Codespaces a producción

**Desarrollo gratuito ≠ producción gratuita.** El desarrollo cuesta 0 € extra
usando la cuota de GitHub Codespaces. Para que la API atienda a usuarios reales
y publique a su hora necesitas un servidor permanente.

---

## 1. Por qué Codespaces no sirve como producción

| | Codespaces | Producción |
|---|---|---|
| Disponibilidad | sólo mientras está encendido | 24/7 |
| Se apaga solo | sí, a los 30 min de inactividad | no |
| Publicaciones programadas | se ejecutan al reanudar el entorno | a su hora exacta |
| URL | cambia al recrear el Codespace | dominio fijo |
| Cuota | horas mensuales limitadas | según tu plan |
| Coste | 0 € dentro de la cuota | desde ~5 €/mes |

**Lo que sí está garantizado**: no se pierde ninguna publicación programada.
La fuente de verdad es la tabla `scheduled_posts` en la base de datos, no la
memoria del proceso. Cuando enciendes el entorno, el barredor recupera todo lo
vencido y lo publica. Simplemente sale tarde.

---

## 2. La lógica de negocio no cambia

Esto es el punto importante del diseño: **migrar no requiere tocar código**.
Sólo cambian variables de entorno y dónde corren los procesos.

| Pieza | Desarrollo | Producción | ¿Cambia el código? |
|---|---|---|---|
| Base de datos | SQLite o PostgreSQL en Docker | PostgreSQL gestionado o en el servidor | No — sólo `DATABASE_URL` |
| Cola de trabajos | Redis en Docker | Redis del servidor o gestionado | No — sólo `REDIS_URL` |
| Publicación | Celery (o *eager*) | Celery en su propio proceso | No — sólo `CELERY_TASK_ALWAYS_EAGER=false` |
| Programación | barredor embebido en la API | `celery beat` aparte | No — sólo `SCHEDULER_IN_PROCESS=false` |
| Videos | disco local | Cloudflare R2 / Amazon S3 | No — sólo `STORAGE_BACKEND=s3` |
| HTTPS | URL de Codespaces | reverse proxy + certificado | No |
| Logs | texto legible | JSON estructurado | No — sólo `LOG_JSON=true` |

---

## 3. Opciones de alojamiento

| Opción | Coste aprox. | Ventajas | Inconvenientes |
|---|---|---|---|
| **VPS** (Hetzner, DigitalOcean, Vultr) | 4–6 €/mes | control total, `docker compose` tal cual | lo administras tú |
| **Plataforma de contenedores** (Fly.io, Railway, Render) | 5–20 €/mes | despliegue desde git, HTTPS incluido | menos control, el almacenamiento es efímero |
| **Kubernetes gestionado** | 30 €+/mes | escala | complejidad innecesaria al principio |

Recomendación para empezar: **un VPS de 2 vCPU / 4 GB** con
`docker compose`. Es lo más parecido a lo que ya tienes funcionando.

---

## 4. Despliegue en un VPS, paso a paso

### 4.1 Preparar el servidor

```bash
ssh root@TU_SERVIDOR

# Usuario sin privilegios para la app
adduser --disabled-password --gecos "" svapi
usermod -aG sudo svapi

# Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker svapi

# Cortafuegos: sólo SSH y HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

> **No abras los puertos 5432 ni 6379 al exterior.** PostgreSQL y Redis se
> comunican por la red interna de Docker.

### 4.2 Clonar y configurar

```bash
su - svapi
git clone https://github.com/mercadomarcelo5559/magoosuna.git
cd magoosuna

cp .env.example .env
nano .env
```

Contenido mínimo del `.env` de producción:

```env
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
LOG_JSON=true

# Dominio real de la API
PUBLIC_BASE_URL=https://api.tudominio.com

# Claves NUEVAS, distintas de las de desarrollo:
#   python -m app.security.crypto --generate-key
#   python -m app.security.crypto --generate-secret
ENCRYPTION_KEY=<clave-fernet-nueva>
SIGNING_SECRET=<secreto-nuevo>
ADMIN_API_KEYS=<clave-admin-nueva>
BOOTSTRAP_API_KEYS=                  # vacío: emite las keys por API

# Sólo el dominio de tu app
CORS_ALLOW_ORIGINS=https://tu-app.macaly.app

# PostgreSQL con contraseña fuerte
POSTGRES_USER=svapi
POSTGRES_PASSWORD=<contraseña-larga-aleatoria>
POSTGRES_DB=social_video_api

# Worker y planificador en procesos propios
CELERY_TASK_ALWAYS_EAGER=false
SCHEDULER_IN_PROCESS=false

# Videos en object storage
STORAGE_BACKEND=s3
S3_BUCKET=mis-videos
S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY_ID=<clave>
S3_SECRET_ACCESS_KEY=<secreto>

# Redirect URI del dominio definitivo
INSTAGRAM_REDIRECT_URI=https://api.tudominio.com/v1/oauth/instagram/callback
TIKTOK_REDIRECT_URI=https://api.tudominio.com/v1/oauth/tiktok/callback
YOUTUBE_REDIRECT_URI=https://api.tudominio.com/v1/oauth/youtube/callback

# …y las credenciales de cada plataforma
```

```bash
chmod 600 .env        # sólo el usuario de la app puede leerlo
```

### 4.3 Levantar el stack

```bash
docker compose up -d --build
docker compose ps           # los 5 servicios en "healthy"/"running"
docker compose logs -f api
```

`docker-compose.yml` ya incluye:

- `postgres` — base de datos con volumen persistente
- `redis` — cola de trabajos
- `api` — aplica las migraciones y arranca uvicorn
- `worker` — publica los videos
- `beat` — dispara las publicaciones programadas

### 4.4 HTTPS con Caddy (la vía más corta)

`/etc/caddy/Caddyfile`:

```caddy
api.tudominio.com {
    encode gzip
    request_body {
        max_size 600MB          # mayor que MAX_VIDEO_SIZE_MB
    }
    reverse_proxy localhost:8000 {
        header_up X-Forwarded-Proto {scheme}
        header_up X-Real-IP {remote_host}
    }
}
```

```bash
sudo apt install -y caddy
sudo systemctl reload caddy
```

Caddy obtiene y renueva el certificado de Let's Encrypt automáticamente.

<details>
<summary>Alternativa con Nginx</summary>

```nginx
server {
    listen 443 ssl http2;
    server_name api.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/api.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.tudominio.com/privkey.pem;

    client_max_body_size 600M;      # mayor que MAX_VIDEO_SIZE_MB
    proxy_read_timeout 600s;        # las subidas tardan

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name api.tudominio.com;
    return 301 https://$host$request_uri;
}
```

Certificado: `sudo certbot --nginx -d api.tudominio.com`
</details>

### 4.5 Dominio

En tu proveedor de DNS, un registro **A**:

```
api.tudominio.com   A   <IP-de-tu-servidor>
```

### 4.6 Actualizar las Redirect URI en las plataformas

**Este paso es obligatorio** o el OAuth dejará de funcionar:

| Plataforma | Dónde |
|---|---|
| Instagram | <https://developers.facebook.com/apps> → tu app → Instagram → Configuración de la API → OAuth redirect URIs |
| TikTok | <https://developers.tiktok.com/apps> → tu app → Login Kit → Redirect URI |
| YouTube | <https://console.cloud.google.com/apis/credentials> → tu ID de cliente → URIs de redireccionamiento autorizados |

### 4.7 Emitir la API key para Macaly

```bash
curl -X POST https://api.tudominio.com/v1/admin/clients \
  -H "Authorization: Bearer $ADMIN_API_KEYS" \
  -H "Content-Type: application/json" \
  -d '{"name": "Macaly (producción)"}'
```

Guarda la `api_key` que devuelve en los secretos de Macaly.

### 4.8 Comprobar

```bash
curl -s https://api.tudominio.com/health | python3 -m json.tool

BASE_URL=https://api.tudominio.com API_KEY=<la-key-nueva> \
  bash scripts/smoke_test.sh
```

Los cinco componentes de `/health` deben estar en `healthy`, incluido
`public_url`.

---

## 5. Object storage (recomendado)

No guardes videos en el disco del servidor: se llena y no escala.

### Cloudflare R2 (sin cargos de salida)

1. <https://dash.cloudflare.com> → **R2** → *Create bucket*.
2. *Manage R2 API Tokens* → crea un token con permiso de lectura/escritura.
3. En el `.env`:

```env
STORAGE_BACKEND=s3
S3_BUCKET=mis-videos
S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY_ID=<access key>
S3_SECRET_ACCESS_KEY=<secret key>
# Opcional: dominio público del bucket (si lo activas)
S3_PUBLIC_BASE_URL=https://videos.tudominio.com
```

### Amazon S3

```env
STORAGE_BACKEND=s3
S3_BUCKET=mis-videos
S3_REGION=eu-west-1
S3_ACCESS_KEY_ID=<AKIA…>
S3_SECRET_ACCESS_KEY=<secreto>
# S3_ENDPOINT_URL se deja vacío
```

Con S3/R2, las URLs que se pasan a Instagram y TikTok son **presignadas** y
temporales (`MEDIA_URL_TTL_MINUTES`), así el bucket puede ser privado.

---

## 6. Copias de seguridad

Lo crítico es **PostgreSQL**: contiene las cuentas conectadas (con sus tokens
cifrados) y el histórico. Los videos son temporales y desechables.

```bash
# /home/svapi/backup.sh
#!/usr/bin/env bash
set -euo pipefail
cd /home/svapi/magoosuna
FECHA=$(date +%F-%H%M)
mkdir -p /home/svapi/backups
docker compose exec -T postgres pg_dump -U svapi social_video_api \
  | gzip > "/home/svapi/backups/bd-$FECHA.sql.gz"
find /home/svapi/backups -name 'bd-*.sql.gz' -mtime +14 -delete
```

```bash
chmod +x /home/svapi/backup.sh
crontab -e
# Copia diaria a las 03:00
0 3 * * * /home/svapi/backup.sh >> /home/svapi/backups/backup.log 2>&1
```

> ⚠️ **Guarda también `ENCRYPTION_KEY` en un gestor de contraseñas.** Sin ella
> los tokens de la copia de seguridad son irrecuperables y habría que
> reconectar todas las cuentas sociales.

Restaurar:

```bash
gunzip -c bd-2026-10-01-0300.sql.gz | \
  docker compose exec -T postgres psql -U svapi social_video_api
```

---

## 7. Monitorización

### Healthcheck externo

Apunta un servicio gratuito (UptimeRobot, Better Stack, Healthchecks.io) a:

```
https://api.tudominio.com/health
```

Alerta si devuelve algo distinto de 200 o si `status` no es `ok`.

### Logs

Con `LOG_JSON=true` los logs salen estructurados y se pueden ingerir en
cualquier plataforma. Cada línea de petición incluye `request_id`, `client_id`,
método, ruta, código y duración. Las publicaciones registran plataforma,
`post_id`, intento, categoría de error y duración. **Nunca** contienen tokens.

```bash
docker compose logs -f api            # peticiones
docker compose logs -f worker         # publicaciones
docker compose logs -f beat           # programación
```

Limita el tamaño de los logs de Docker añadiendo a cada servicio:

```yaml
logging:
  driver: json-file
  options: { max-size: "10m", max-file: "3" }
```

### Consultas útiles

```sql
-- Publicaciones fallidas del último día, por plataforma
SELECT platform, error_category, count(*)
FROM posts
WHERE status = 'failed' AND created_at > now() - interval '1 day'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Cuentas con el token a punto de caducar
SELECT platform, account_name, token_expiration
FROM social_accounts
WHERE is_active AND token_expiration < now() + interval '7 days';

-- Publicaciones programadas pendientes
SELECT run_at, status, count(*)
FROM scheduled_posts WHERE status = 'pending'
GROUP BY 1, 2 ORDER BY 1;
```

---

## 8. Actualizar la aplicación

```bash
cd /home/svapi/magoosuna
git pull
docker compose up -d --build          # aplica migraciones al arrancar `api`
docker compose ps
curl -s https://api.tudominio.com/health | python3 -m json.tool
```

Las migraciones se ejecutan automáticamente (`alembic upgrade head` en el
comando del servicio `api`). Haz una copia de seguridad antes de actualizar si
la versión trae cambios de esquema.

---

## 9. Ajustes de rendimiento

Cuando crezca el uso:

```env
# Más conexiones a la base de datos
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10

# Rate limiting por cliente
RATE_LIMIT_REQUESTS=600
RATE_LIMIT_WINDOW_SECONDS=60
```

```yaml
# docker-compose.yml: más procesos de API y de worker
api:
  command: >
    sh -c "alembic upgrade head &&
           uvicorn app.main:app --host 0.0.0.0 --port 8000
                  --workers 4 --proxy-headers"

worker:
  command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
```

Puedes escalar los workers horizontalmente (`docker compose up -d --scale
worker=3`): la cola de Redis reparte el trabajo y los reintentos siguen
coordinados por la base de datos.

> `beat` debe correr en **una sola instancia**, o las publicaciones
> programadas se despacharían varias veces.

---

## 10. Lista de comprobación antes de abrir al público

- [ ] `ENVIRONMENT=production` y `DEBUG=false`
- [ ] `ENCRYPTION_KEY` y `SIGNING_SECRET` **nuevos** (distintos de desarrollo)
      y guardados en un gestor de contraseñas
- [ ] `BOOTSTRAP_API_KEYS` vacío; las keys se emiten por API
- [ ] `CORS_ALLOW_ORIGINS` con el dominio exacto de Macaly (no `*`)
- [ ] `.env` con permisos `600` y fuera de git
- [ ] PostgreSQL con contraseña fuerte y **sin** puerto expuesto al exterior
- [ ] Redis **sin** puerto expuesto al exterior
- [ ] HTTPS funcionando y renovación automática del certificado
- [ ] Redirect URI actualizadas en Instagram, TikTok y YouTube
- [ ] `STORAGE_BACKEND=s3` configurado
- [ ] `CELERY_TASK_ALWAYS_EAGER=false` y `SCHEDULER_IN_PROCESS=false`
- [ ] Exactamente **un** proceso `beat`
- [ ] Copia de seguridad diaria probada (¡y restauración probada!)
- [ ] Healthcheck externo con alertas
- [ ] `bash scripts/smoke_test.sh` en verde contra el dominio real
- [ ] Cuotas revisadas: App Review de Meta, audit de TikTok, cuota de YouTube

---

## 11. URL pública HTTPS durante el desarrollo

Si necesitas una URL pública **antes** de tener servidor, para probar el OAuth:

### Opción 1 — Codespaces con el puerto público (recomendada)

Ya tienes HTTPS: pestaña *PORTS* → puerto 8000 → *Port Visibility* →
**Public**. La URL `https://<codespace>-8000.app.github.dev` es estable
mientras no recrees el Codespace.

### Opción 2 — Cloudflare Tunnel

```bash
# Instalar (una vez)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# Túnel efímero, sin cuenta
cloudflared tunnel --url http://localhost:8000
# → https://algo-aleatorio.trycloudflare.com
```

Pon esa URL en `PUBLIC_BASE_URL` y en las Redirect URI de las plataformas.

> **El sistema no depende del túnel.** Es sólo una URL pública alternativa: la
> API funciona igual sin él (salvo los callbacks OAuth y que Instagram no
> podría descargar el video, para lo que se usa la subida resumible). La URL
> cambia en cada ejecución del túnel efímero, así que para algo estable usa
> Codespaces público o un dominio propio.
