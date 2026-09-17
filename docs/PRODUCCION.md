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
| Cola de trabajos | la base de datos | la base de datos (Redis sólo si escalas) | No — sólo `PUBLISH_MODE` |
| Publicación | hilos del proceso (`solo`) | los mismos hilos, o Celery si escalas | No — sólo `PUBLISH_MODE` |
| Programación | barredor embebido | el mismo barredor, o `celery beat` | No — sólo `SCHEDULER_IN_PROCESS` |
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

Recomendación para empezar: **un VPS de 2 vCPU / 4 GB** (Hetzner CX22 ~4 €/mes,
DigitalOcean ~6 $/mes). El script de la sección 4 lo deja funcionando con un
solo comando, y al usar un único servicio no necesitas Redis gestionado.

---

## 4. Despliegue en un VPS: un solo comando

### 4.1 Antes de nada: el DNS

Crea un registro **A** en tu proveedor de dominios apuntando al servidor:

```
api.tudominio.com   A   <IP-de-tu-VPS>
```

Hazlo primero: Let's Encrypt necesita resolver el dominio para emitir el
certificado.

### 4.2 El comando

Conéctate al VPS (desde el terminal del Codespace, también vale desde el iPad):

```bash
ssh root@<IP-de-tu-VPS>
```

Y ejecuta:

```bash
curl -fsSL https://raw.githubusercontent.com/mercadomarcelo5559/magoosuna/main/deploy/install.sh \
  | bash -s -- api.tudominio.com tu@correo.com
```

Eso es todo. El script deja funcionando:

| | |
|---|---|
| Docker | instalado y arrancando al reiniciar |
| Cortafuegos | sólo SSH, HTTP y HTTPS (PostgreSQL **no** se expone) |
| Usuario de servicio | `svapi`, sin privilegios |
| `.env` | generado con claves nuevas y permisos `600` |
| PostgreSQL 16 | con contraseña aleatoria, en la red interna |
| La API | un solo servicio (API + worker + planificador) |
| HTTPS | certificado de Let's Encrypt, renovación automática (Caddy) |
| Copia de seguridad | diaria a las 03:00, conserva 14 días |
| `svapi-update` | actualizar a la última versión |
| `svapi-backup` | copia de seguridad manual |

Al terminar te imprime:

* la URL de la API y de Swagger,
* tu **API key de cliente** (para Macaly), guardada en `/root/api-key-cliente.txt`,
* tu API key de administración, en `/root/api-key-admin.txt`,
* las tres **Redirect URI** que tienes que registrar en Instagram, TikTok y YouTube.

### 4.3 Comprobar

```bash
curl -s https://api.tudominio.com/health | python3 -m json.tool
```

Los componentes deben estar todos en `healthy`. Y desde tu iPad:

```
https://api.tudominio.com/docs
```

### 4.4 Pega tus credenciales de plataforma

El script no puede inventarse tus credenciales de Meta, TikTok y Google
(ver README §7). Cuando las tengas:

```bash
cd /opt/social-video-api
nano .env          # pega INSTAGRAM_APP_ID, TIKTOK_CLIENT_KEY, YOUTUBE_CLIENT_ID…
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d
```

### 4.5 Actualizar más adelante

```bash
svapi-update       # copia de seguridad + git pull + rebuild + migraciones
```

### 4.6 Por qué un solo servicio

El despliegue usa `PUBLISH_MODE=solo`: la API, el worker de publicaciones y
el planificador comparten proceso, y **la base de datos hace de cola**. Eso
significa:

* **Dos contenedores** en total (la API y PostgreSQL) en lugar de cinco.
* **Sin Redis**, que en los servicios gestionados es la pieza más cara.
* Un VPS de 2 vCPU / 4 GB va sobrado.

La reclamación de trabajos es atómica en base de datos
(`UPDATE ... WHERE status = 'queued'`), así que no hay publicaciones
duplicadas ni aunque arranques varios procesos.

Si algún día necesitas escalar, se separa en workers Celery sin tocar la
lógica de negocio:

```bash
docker compose -f deploy/docker-compose.prod.yml \
               -f deploy/docker-compose.celery.yml --env-file .env up -d
```

Eso añade Redis, `worker` y `beat`, y cambia el modo a `celery`. Los mismos
trabajos (`app/services/jobs.py`) los ejecutan ambos caminos, así que no
pueden desincronizarse.

### 4.7 Si algo falla

```bash
cd /opt/social-video-api
docker compose -f deploy/docker-compose.prod.yml --env-file .env ps
docker compose -f deploy/docker-compose.prod.yml --env-file .env logs -f api
docker compose -f deploy/docker-compose.prod.yml --env-file .env logs caddy
```

| Síntoma | Causa habitual |
|---|---|
| El certificado no se emite | El DNS aún no propaga, o el puerto 80 está cerrado |
| `password authentication failed` | Reutilizaste un volumen de PostgreSQL con otra contraseña: `docker compose ... down -v` y vuelve a levantar (borra los datos) |
| La API reinicia en bucle | Mira `logs api`: casi siempre falta una variable en el `.env` |
| 502 desde Caddy | La API todavía está aplicando migraciones; espera un minuto |

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

**El script de instalación ya las configura**: copia diaria a las 03:00 en
`/opt/social-video-api/backups`, conservando 14 días. Para lanzarla a mano:

```bash
svapi-backup
ls -la /opt/social-video-api/backups
```

> ⚠️ **Guarda también `ENCRYPTION_KEY` en un gestor de contraseñas.** Sin ella
> los tokens de la copia de seguridad son irrecuperables y habría que
> reconectar todas las cuentas sociales.

Restaurar:

```bash
cd /opt/social-video-api
gunzip -c backups/bd-2026-10-01-0300.sql.gz | \
  docker compose -f deploy/docker-compose.prod.yml --env-file .env \
    exec -T postgres psql -U svapi social_video_api
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
svapi-update
```

Eso hace copia de seguridad, trae los cambios, reconstruye la imagen, aplica
las migraciones y comprueba `/health`. Manualmente sería:

```bash
cd /opt/social-video-api
svapi-backup
git pull
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
curl -s https://api.tudominio.com/health | python3 -m json.tool
```

Las migraciones se ejecutan automáticamente (`alembic upgrade head` en el
comando del servicio `api`). Haz una copia de seguridad antes de actualizar si
la versión trae cambios de esquema.

---

## 9. Ajustes de rendimiento

Cuando crezca el uso:

```env
# Más publicaciones simultáneas en modo solo
PUBLISH_CONCURRENCY=6

# Más conexiones a la base de datos
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10

# Rate limiting por cliente
RATE_LIMIT_REQUESTS=600
RATE_LIMIT_WINDOW_SECONDS=60
```

Si un solo servicio se queda corto, pasa a Celery (sección 4.6) y escala los
workers horizontalmente:

```bash
docker compose -f deploy/docker-compose.prod.yml \
               -f deploy/docker-compose.celery.yml --env-file .env \
               up -d --scale worker=3
```

> Con `PUBLISH_MODE=solo`, **no** subas `--workers` de uvicorn por encima de 1:
> el planificador embebido debe ejecutarse en un único proceso. Si necesitas
> varios procesos de API, ese es el momento de pasar a Celery.

---

## 10. Lista de comprobación antes de abrir al público

- [ ] `ENVIRONMENT=production` y `DEBUG=false`
- [ ] `ENCRYPTION_KEY` y `SIGNING_SECRET` **nuevos** (distintos de desarrollo)
      y guardados en un gestor de contraseñas
- [ ] `BOOTSTRAP_API_KEYS` vacío; las keys se emiten por API
- [ ] `CORS_ALLOW_ORIGINS` con el dominio exacto de Macaly (no `*`)
- [ ] `.env` con permisos `600` y fuera de git
- [ ] PostgreSQL con contraseña fuerte y **sin** puerto expuesto al exterior
- [ ] HTTPS funcionando y renovación automática del certificado
- [ ] Redirect URI actualizadas en Instagram, TikTok y YouTube
- [ ] `STORAGE_BACKEND=s3` configurado
- [ ] `PUBLISH_MODE=solo` y `SCHEDULER_IN_PROCESS=true` (o `celery` + un único `beat` si escalaste)
- [ ] Un solo proceso de uvicorn (el planificador embebido debe ser único)
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
