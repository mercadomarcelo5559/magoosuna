# Social Video API

API REST **independiente** para gestionar y publicar videos en redes sociales
(**Instagram**, **TikTok** y **YouTube**), construida con FastAPI.

Está pensada para que **Macaly sea únicamente el cliente/frontend**: toda la
lógica de OAuth, subida, publicación, programación, reintentos y estados vive
aquí. La API funciona con cualquier cliente (Macaly, curl, una app móvil…).

```
┌──────────────┐   Bearer API key    ┌─────────────────────┐   OAuth 2.0    ┌──────────────┐
│    Macaly    │ ──────────────────► │  Social Video API   │ ─────────────► │  Instagram   │
│  (frontend)  │ ◄────────────────── │  FastAPI + Celery   │ ─────────────► │   TikTok     │
└──────────────┘    JSON / estados   └─────────────────────┘ ─────────────► │   YouTube    │
                                        │            │                     └──────────────┘
                                   PostgreSQL      Redis
                                   (datos)      (cola de trabajos)
```

---

## Índice

1. [Estado del proyecto](#1-estado-del-proyecto)
2. [Entorno de desarrollo: GitHub Codespaces](#2-entorno-de-desarrollo-github-codespaces)
3. [Arranque rápido](#3-arranque-rápido)
4. [Estructura del proyecto](#4-estructura-del-proyecto)
5. [Comandos exactos](#5-comandos-exactos)
6. [Variables de entorno](#6-variables-de-entorno)
7. [Credenciales: qué necesitas y dónde conseguirlo](#7-credenciales-qué-necesitas-y-dónde-conseguirlo)
8. [Cómo conectar Instagram](#8-cómo-conectar-instagram)
9. [Cómo conectar TikTok](#9-cómo-conectar-tiktok)
10. [Cómo conectar YouTube](#10-cómo-conectar-youtube)
11. [Cómo probar una publicación](#11-cómo-probar-una-publicación)
12. [Integración con Macaly](#12-integración-con-macaly)
13. [Estados, reintentos e idempotencia](#13-estados-reintentos-e-idempotencia)
14. [Qué requiere aprobación externa](#14-qué-requiere-aprobación-externa)
15. [Trabajar sólo desde el iPad](#15-trabajar-sólo-desde-el-ipad)
16. [De Codespaces a producción](#16-de-codespaces-a-producción)
17. [Seguridad](#17-seguridad)
18. [Tests y verificación](#18-tests-y-verificación)

---

## 1. Estado del proyecto

Todo lo que no depende de credenciales externas está **implementado y
verificado ejecutándose**:

| Componente | Estado |
|---|---|
| API REST (30 rutas, Swagger) | ✅ funcionando |
| PostgreSQL 16 + 10 tablas + Alembic (ida y vuelta) | ✅ verificado |
| Redis + Celery (9 tareas) | ✅ worker conectado y publicando |
| Publicaciones programadas (barredor real) | ✅ despachadas al llegar la hora |
| Cifrado de tokens OAuth (Fernet) | ✅ verificado en la BD |
| Idempotencia (`Idempotency-Key`) | ✅ verificada (sin duplicados) |
| Reintentos con backoff + clasificación de errores | ✅ verificado contra Google real |
| Subida, validación y descarga firmada de video | ✅ verificado byte a byte |
| Rate limiting, CORS, logs sin secretos | ✅ verificado |
| Docker + docker compose | ✅ imagen construida y arrancada |
| Tests: **251 pasando**, 85 % de cobertura | ✅ |
| Lint (ruff) y formato | ✅ limpio |

**Falta únicamente**: pegar tus credenciales de Meta, TikTok y Google en el
`.env` (sección 7) y solicitar las aprobaciones externas (sección 14). El
código de los tres providers usa los endpoints oficiales vigentes y está
probado con respuestas HTTP simuladas de cada plataforma.

---

## 2. Entorno de desarrollo: GitHub Codespaces

El proyecto está preparado para **GitHub Codespaces**, de modo que puedas
trabajar desde el navegador del iPad sin tener ningún ordenador encendido.

### Cómo crear el Codespace (desde el iPad)

1. Abre **Safari** (o Chrome) y entra en
   `https://github.com/mercadomarcelo5559/magoosuna`
2. Pulsa el botón verde **`< > Code`**.
3. Pestaña **`Codespaces`** → **`Create codespace on main`**.
   *(Si ya tienes uno, aparecerá en la lista: púlsalo para reanudarlo.)*
4. Espera 2–3 minutos. El `.devcontainer/devcontainer.json` instala
   automáticamente:
   - Python 3.12
   - Git
   - Docker-in-Docker (para PostgreSQL y Redis)
   - todas las dependencias (FastAPI, Alembic, pytest, Celery…)
   - un `.env` con **claves generadas** y `PUBLIC_BASE_URL` ya apuntando a la
     URL de tu Codespace
5. Cuando termine verás en el terminal el mensaje `Social Video API — entorno listo`.

> **Consejo para el iPad**: añade la URL del Codespace a la pantalla de inicio
> (Compartir → *Añadir a pantalla de inicio*). Se abre como una app.

### Cuota gratuita

GitHub Free incluye una cuota mensual de Codespaces para cuentas personales
(horas de núcleo y almacenamiento). Para no gastarla:

- El devcontainer pide la máquina más pequeña (**2 núcleos / 4 GB**).
- PostgreSQL y Redis están limitados en memoria en `docker-compose.yml`
  (`shared_buffers=128MB`, `maxmemory=128mb`).
- **Detén el Codespace cuando termines**: menú ☰ → *Stop Current Codespace*.
  Un Codespace detenido no consume horas.
- Consulta tu consumo en <https://github.com/settings/billing>.
- No se usa GPU ni nada que requiera una máquina grande.

> ⚠️ **Codespaces NO es un servidor de producción.** Mientras esté detenido no
> publica nada: las publicaciones programadas esperarán a que lo enciendas (el
> barredor recupera todo lo vencido al arrancar, porque la fuente de verdad es
> la tabla `scheduled_posts`, no la memoria). Para publicar 24/7 mira la
> [sección 16](#16-de-codespaces-a-producción).

---

## 3. Arranque rápido

Dentro del Codespace (o en cualquier máquina con Python 3.12):

```bash
# 1. Dependencias y .env  (el devcontainer ya lo hace por ti)
make install
make env
make keys          # copia las claves generadas al .env

# 2. Base de datos y cola  (si hay Docker; si no, se usa SQLite y no hace falta)
make up            # PostgreSQL + Redis
make migrate       # crea las tablas

# 3. Arrancar todo
make all-in-one    # API + worker (+ planificador)
```

Abre **`/docs`** para el Swagger interactivo:
- en Codespaces: `https://<tu-codespace>-8000.app.github.dev/docs`
- en local: <http://localhost:8000/docs>

Comprueba que todo está sano:

```bash
make health        # estado de base de datos, Redis, almacenamiento y scheduler
make smoke         # 17 comprobaciones de extremo a extremo
```

### Modo mínimo (sin Docker)

Si Docker no está disponible, el proyecto funciona igual con SQLite y sin Redis:

```bash
# en el .env:
DATABASE_URL=sqlite:///./data/social_video_api.db
CELERY_TASK_ALWAYS_EAGER=true    # las publicaciones corren dentro de la API
SCHEDULER_IN_PROCESS=true        # el barredor va embebido en la API

make dev
```

---

## 4. Estructura del proyecto

```
.
├── .devcontainer/
│   ├── devcontainer.json       Configuración del Codespace
│   ├── post-create.sh          Instalación + .env + migraciones (una vez)
│   └── post-start.sh           Reanudar PostgreSQL/Redis (cada arranque)
│
├── app/
│   ├── main.py                 App FastAPI, middleware, manejo de errores
│   ├── config.py               Toda la configuración vía variables de entorno
│   ├── database.py             Engine y sesiones SQLAlchemy
│   ├── deps.py                 Autenticación, rate limiting, paginación
│   ├── logging_config.py       Logs con redacción de secretos
│   │
│   ├── models/                 Tablas SQLAlchemy
│   │   ├── client.py             Client, ApiKey
│   │   ├── social_account.py     SocialAccount (tokens cifrados)
│   │   ├── media.py              MediaAsset
│   │   ├── post.py               PostGroup, Post, PostAttempt, ScheduledPost
│   │   ├── idempotency.py        IdempotencyRecord
│   │   ├── oauth.py              OAuthState
│   │   └── enums.py              Platform, PostStatus, ErrorCategory…
│   │
│   ├── schemas/                Modelos Pydantic de entrada/salida
│   │
│   ├── routers/                Endpoints HTTP
│   │   ├── health.py             /health, /v1/platforms
│   │   ├── oauth.py              /v1/oauth/{platform}/authorize|callback
│   │   ├── accounts.py           /v1/accounts…
│   │   ├── media.py              /v1/media…
│   │   ├── posts.py              /v1/posts…
│   │   ├── webhooks.py           /v1/webhooks…
│   │   └── admin.py              /v1/admin… (clientes y API keys)
│   │
│   ├── services/               Lógica de negocio
│   │   ├── clients.py            Clientes y rotación de API keys
│   │   ├── accounts.py           Credenciales, refresh automático, desconexión
│   │   ├── media.py              Ingesta, URLs firmadas, retención
│   │   ├── posts.py              Fan-out multiplataforma y programación
│   │   ├── publisher.py          Motor de publicación (estados + intentos)
│   │   ├── idempotency.py        Idempotency-Key
│   │   ├── retry.py              Clasificación de errores y backoff
│   │   ├── scheduler.py          Barredor embebido (APScheduler) para dev
│   │   └── rate_limit.py         Rate limiting (Redis o memoria)
│   │
│   ├── providers/              Una carpeta por plataforma
│   │   ├── base.py               Contrato `BaseProvider` (añadir plataforma = 3 pasos)
│   │   ├── errors.py             Errores clasificados (transient/auth/permanent…)
│   │   ├── registry.py           Registro de providers
│   │   ├── instagram/provider.py Instagram Content Publishing API
│   │   ├── tiktok/provider.py    TikTok Content Posting API v2
│   │   └── youtube/provider.py   YouTube Data API v3
│   │
│   ├── storage/                Almacenamiento de video
│   │   ├── base.py               Contrato
│   │   ├── local.py              Disco local (desarrollo)
│   │   └── s3.py                 S3 / Cloudflare R2 (producción)
│   │
│   ├── workers/                Trabajos en segundo plano
│   │   ├── celery_app.py         Configuración de Celery + beat
│   │   └── tasks.py              publicar, reintentar, refrescar, limpiar
│   │
│   └── utils/                  http.py, video.py, polling.py
│
├── alembic/                    Migraciones (0001_esquema_inicial)
├── tests/                      251 tests (pytest); ninguno publica de verdad
├── scripts/                    dev.sh, smoke_test.sh, check_secrets.sh
├── docs/                       Documentación ampliada
│   ├── MACALY.md                 Guía de integración para Macaly
│   ├── IPAD.md                   Trabajar sólo desde el iPad
│   ├── PRODUCCION.md             Migración a producción
│   └── PLATAFORMAS.md            Detalle de cada red social
│
├── Dockerfile                  Imagen de la API y del worker
├── docker-compose.yml          api + worker + beat + postgres + redis
├── Makefile                    Todos los comandos
├── requirements.txt            Dependencias de ejecución
├── requirements-dev.txt        + herramientas de desarrollo
├── .env.example                Plantilla documentada de configuración
└── pyproject.toml              pytest, ruff, mypy, coverage
```

---

## 5. Comandos exactos

```bash
# ---------- Instalación ----------
make install         # instala dependencias
make env             # crea .env desde .env.example
make keys            # genera ENCRYPTION_KEY, SIGNING_SECRET y API keys

# ---------- Servicios ----------
make up              # PostgreSQL + Redis (Docker)
make down            # parar (conserva datos)
make reset           # parar y BORRAR datos
make stack           # TODO en Docker: api + worker + beat + bd + redis
make logs            # seguir los logs de Docker

# ---------- Desarrollo ----------
make dev             # API con recarga automática  → /docs
make worker          # worker de publicaciones (Celery)
make beat            # planificador de publicaciones programadas
make all-in-one      # API + worker + beat en un comando

# ---------- Base de datos ----------
make migrate                      # aplicar migraciones
make migration m="lo que cambia"  # crear una migración nueva
make downgrade                    # revertir la última
make db-status                    # revisión actual e historial

# ---------- Calidad ----------
make test            # tests
make test-cov        # tests con cobertura
make lint            # estilo
make format          # formatear y autocorregir
make typecheck       # tipos (mypy)
make check           # lint + tests (lo que valida la CI)
make secrets         # buscar secretos hardcodeados

# ---------- Comprobaciones ----------
make health          # estado del servicio
make smoke           # 17 comprobaciones de extremo a extremo
make clean           # limpiar caches
```

**Parar la API**: `Ctrl+C` en el terminal. Con Docker: `make down`.

---

## 6. Variables de entorno

El fichero **`.env.example`** documenta cada variable con su propósito y dónde
obtener su valor. Copia y rellena:

```bash
cp .env.example .env
make keys     # y pega el resultado en el .env
```

### Imprescindibles

| Variable | Para qué sirve | Cómo obtenerla |
|---|---|---|
| `ENCRYPTION_KEY` | Cifra los tokens OAuth en la BD | `python -m app.security.crypto --generate-key` |
| `SIGNING_SECRET` | Firma las URLs de descarga y valida webhooks de Meta | `python -m app.security.crypto --generate-secret` |
| `BOOTSTRAP_API_KEYS` | La API key que usará Macaly | `python -m app.security.crypto --generate-api-key` |
| `ADMIN_API_KEYS` | Crear clientes y rotar API keys | igual que la anterior (usa prefijo `adm_`) |
| `PUBLIC_BASE_URL` | URL pública de la API (OAuth + descarga de video) | En Codespaces se rellena sola |
| `DATABASE_URL` | Base de datos | `sqlite:///./data/...` o `postgresql+psycopg://…` |
| `REDIS_URL` | Cola de trabajos | `redis://localhost:6379/0` |

### Credenciales de plataforma

| Variable | Plataforma |
|---|---|
| `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_REDIRECT_URI` | Instagram |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` | TikTok |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI` | YouTube |

### Ajustes útiles

| Variable | Por defecto | Qué hace |
|---|---|---|
| `MAX_VIDEO_SIZE_MB` | `512` | Tamaño máximo de video aceptado |
| `MEDIA_RETENTION_HOURS` | `24` | Cuándo se borran los videos del servidor |
| `MAX_PUBLISH_ATTEMPTS` | `5` | Reintentos antes de marcar `failed` |
| `RATE_LIMIT_REQUESTS` | `120` | Peticiones por minuto y por API key |
| `CORS_ALLOW_ORIGINS` | `*` | Dominios permitidos (pon el de Macaly en producción) |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | `true` = publicar sin Redis (dentro de la API) |
| `SCHEDULER_IN_PROCESS` | `true` | `true` = barredor embebido (dev); `false` = `celery beat` |
| `STORAGE_BACKEND` | `local` | `local` o `s3` (S3 / Cloudflare R2) |
| `TIKTOK_POST_MODE` | `DIRECT_POST` | `DIRECT_POST` publica; `INBOX` deja borrador |
| `TIKTOK_AUDIT_PASSED` | `false` | Ponlo a `true` cuando TikTok apruebe tu app |
| `YOUTUBE_DEFAULT_PRIVACY` | `private` | `private`, `unlisted` o `public` |

> **`.env` nunca se sube al repositorio** (está en `.gitignore`). Lo que se
> versiona es `.env.example`, sin valores.

---

## 7. Credenciales: qué necesitas y dónde conseguirlo

No se inventa ninguna credencial. Esto es exactamente lo que tienes que
conseguir tú, y dónde va cada cosa:

| # | Credencial | Dónde se obtiene | Variable del `.env` | Endpoint que la usa |
|---|---|---|---|---|
| 1 | Instagram App ID | <https://developers.facebook.com/apps> → tu app → Instagram → Configuración de la API | `INSTAGRAM_APP_ID` | `/v1/oauth/instagram/authorize` |
| 2 | Instagram App Secret | mismo sitio | `INSTAGRAM_APP_SECRET` | `/v1/oauth/instagram/callback` |
| 3 | Instagram Redirect URI | debes **registrarla** en esa misma pantalla | `INSTAGRAM_REDIRECT_URI` | `/v1/oauth/instagram/callback` |
| 4 | TikTok Client Key | <https://developers.tiktok.com/apps> → tu app | `TIKTOK_CLIENT_KEY` | `/v1/oauth/tiktok/authorize` |
| 5 | TikTok Client Secret | mismo sitio | `TIKTOK_CLIENT_SECRET` | `/v1/oauth/tiktok/callback` |
| 6 | TikTok Redirect URI | **registrarla** en Login Kit → Redirect URI | `TIKTOK_REDIRECT_URI` | `/v1/oauth/tiktok/callback` |
| 7 | Google Client ID | <https://console.cloud.google.com/apis/credentials> → ID de cliente OAuth → *Aplicación web* | `YOUTUBE_CLIENT_ID` | `/v1/oauth/youtube/authorize` |
| 8 | Google Client Secret | mismo sitio | `YOUTUBE_CLIENT_SECRET` | `/v1/oauth/youtube/callback` |
| 9 | Google Redirect URI | **registrarla** en “URIs de redireccionamiento autorizados” | `YOUTUBE_REDIRECT_URI` | `/v1/oauth/youtube/callback` |

Las **Redirect URI** deben coincidir **carácter por carácter** con lo que
registres en cada plataforma. En Codespaces son:

```
https://<tu-codespace>-8000.app.github.dev/v1/oauth/instagram/callback
https://<tu-codespace>-8000.app.github.dev/v1/oauth/tiktok/callback
https://<tu-codespace>-8000.app.github.dev/v1/oauth/youtube/callback
```

El script del devcontainer las imprime al crear el Codespace. También puedes
verlas en cualquier momento:

```bash
grep REDIRECT_URI .env
```

> **Importante**: Instagram y TikTok exigen **HTTPS**. La URL de Codespaces ya
> es HTTPS, pero el puerto 8000 debe estar en visibilidad **Public**
> (ver [sección 15](#15-trabajar-sólo-desde-el-ipad)).

---

## 8. Cómo conectar Instagram

**Implementación**: `app/providers/instagram/provider.py`
**Documentación oficial consultada**:
<https://developers.facebook.com/docs/instagram-platform/content-publishing>

### Requisitos de la plataforma (validados en el código)

- La cuenta debe ser **Professional** (*Business* o *Creator*). Las cuentas
  personales **no pueden publicar por API**: la API lo comprueba al conectar y
  devuelve un error explicándolo.
  Cambiar el tipo: app de Instagram → *Configuración* → *Tipo de cuenta*.
- Permisos: `instagram_business_basic` + `instagram_business_content_publish`
  (modo *Business Login for Instagram*, el recomendado).
  Si usas `INSTAGRAM_LOGIN_MODE=facebook`: `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`,
  y la cuenta de Instagram debe estar vinculada a una Página de Facebook.
- Límite oficial: **100 publicaciones por API cada 24 h** y por cuenta.
  Consultable en `GET /v1/accounts/{id}/publishing-limit`.

### Pasos

1. Crea la app en <https://developers.facebook.com/apps> y añade el producto
   **Instagram**.
2. Copia el *Instagram App ID* y el *App Secret* al `.env`.
3. Registra la Redirect URI (sección 7) en *Instagram → Configuración de la API*.
4. Reinicia la API y comprueba que ya está configurada:
   ```bash
   curl -H "Authorization: Bearer $API_KEY" $BASE/v1/platforms
   # instagram → "configured": true
   ```
5. Pide la URL de autorización y ábrela en el navegador:
   ```bash
   curl -H "Authorization: Bearer $API_KEY" \
     "$BASE/v1/oauth/instagram/authorize?return_url=https://tu-app.macaly.app/ok"
   ```
6. Acepta en Instagram. La API recibe el `code`, lo canjea por un token de
   larga duración (60 días), valida que la cuenta es profesional y la guarda
   con el token **cifrado**.
7. Verifica:
   ```bash
   curl -H "Authorization: Bearer $API_KEY" $BASE/v1/accounts?platform=instagram
   ```

### Flujo de publicación que implementa la API

| Paso | Endpoint oficial |
|---|---|
| 1. Crear contenedor | `POST /{ig-user-id}/media` con `media_type=REELS` |
| 1b. Subir el fichero | `POST https://rupload.facebook.com/ig-api-upload/v25.0/{container-id}` (cabeceras `Authorization: OAuth`, `offset`, `file_size`) |
| 2. Esperar el procesado | `GET /{container-id}?fields=status_code` hasta `FINISHED` |
| 3. Publicar | `POST /{ig-user-id}/media_publish` con `creation_id` |
| 4. Obtener la URL | `GET /{media-id}?fields=permalink` |

Si el video tiene una URL pública alcanzable se usa `video_url` (un paso
menos). Si no, se usa la **subida resumible**. La renovación del token de 60
días es automática (`grant_type=ig_refresh_token`).

---

## 9. Cómo conectar TikTok

**Implementación**: `app/providers/tiktok/provider.py`
**Documentación oficial consultada**:
<https://developers.tiktok.com/doc/content-posting-api-get-started/>

### ⚠️ Auditoría obligatoria de TikTok

Esto **no se puede sortear** y conviene que lo sepas antes de empezar:

> Mientras tu app **no haya pasado el *audit*** de TikTok, **todo el contenido
> publicado queda restringido a visibilidad privada** (`SELF_ONLY`).

La API refleja ese hecho: con `TIKTOK_AUDIT_PASSED=false` (por defecto) pide
`SELF_ONLY`, porque pedir `PUBLIC_TO_EVERYONE` sería engañoso. Cuando TikTok
te apruebe, pon `TIKTOK_AUDIT_PASSED=true` y pasará a pedir público.

**Cómo solicitar el audit**: panel de tu app → *Content Posting API* →
*Submit for review*. TikTok pide una demo del flujo de publicación.

### Pasos

1. Cuenta de developer en <https://developers.tiktok.com> → *Manage apps* →
   crear app.
2. Añade los productos **Login Kit** y **Content Posting API**.
3. Copia *Client key* y *Client secret* al `.env`.
4. Registra la Redirect URI (sección 7) en *Login Kit → Redirect URI*.
5. Solicita los scopes:
   - `user.info.basic` — identidad de la cuenta
   - `video.publish` — **Direct Post** (publica directamente)
   - `video.upload` — deja el video en los borradores de la app de TikTok
6. Si vas a publicar pasando una URL (`PULL_FROM_URL`), **verifica la
   propiedad del dominio** en el panel (*URL prefix verification*). Sin eso
   TikTok responde `url_ownership_unverified`.
7. Conecta la cuenta igual que Instagram:
   `GET /v1/oauth/tiktok/authorize`.
8. Consulta las opciones que permite el creador antes de publicar:
   ```bash
   curl -H "Authorization: Bearer $API_KEY" \
     $BASE/v1/accounts/{account_id}/creator-info
   ```

### Flujo de publicación que implementa la API

| Paso | Endpoint oficial |
|---|---|
| 1. Información del creador (obligatorio) | `POST /v2/post/publish/creator_info/query/` |
| 2. Inicializar | `POST /v2/post/publish/video/init/` (Direct Post) o `/v2/post/publish/inbox/video/init/` (borradores) |
| 3. Subir | `PUT <upload_url>` con `Content-Range` (chunks de 64 MB; ficheros < 64 MB en una sola petición) |
| 4. Estado | `POST /v2/post/publish/status/fetch/` hasta `PUBLISH_COMPLETE` |

Tokens: access token de 24 h, refresh token de 365 días; la renovación es
automática. Límite oficial: **6 peticiones/minuto** por token en los
endpoints de inicialización.

### Opciones por plataforma

```json
{
  "platform_options": {
    "tiktok": {
      "privacy_level": "PUBLIC_TO_EVERYONE",
      "disable_comment": false,
      "disable_duet": false,
      "disable_stitch": false,
      "video_cover_timestamp_ms": 1000,
      "brand_content_toggle": false,
      "is_aigc": false,
      "post_mode": "DIRECT_POST"
    }
  }
}
```

---

## 10. Cómo conectar YouTube

**Implementación**: `app/providers/youtube/provider.py`
**Documentación oficial consultada**:
<https://developers.google.com/youtube/v3/docs/videos/insert>

### Pasos

1. Crea un proyecto en <https://console.cloud.google.com>.
2. *APIs y servicios* → *Biblioteca* → habilita **YouTube Data API v3**.
3. *Pantalla de consentimiento OAuth*: complétala y añade tu cuenta de Google
   como **Usuario de prueba** mientras la app esté en modo *Testing*.
4. *Credenciales* → *Crear credenciales* → **ID de cliente de OAuth** → tipo
   **Aplicación web**. Copia *Client ID* y *Client secret* al `.env`.
5. Registra la Redirect URI (sección 7) en *URIs de redireccionamiento
   autorizados*.
6. Conecta el canal: `GET /v1/oauth/youtube/authorize`.
   La API pide `access_type=offline` y `prompt=consent`, necesarios para
   recibir **refresh token** (si Google no lo devuelve, la API te dice
   exactamente qué hacer: revocar en
   <https://myaccount.google.com/permissions> y reconectar).

### ⚠️ Cuota y auditoría de Google

- `videos.insert` cuesta **1600 unidades**; la cuota diaria por defecto es de
  **10 000 unidades** → unas **6 subidas al día**. Se amplía solicitándolo a
  Google desde la consola.
- Los proyectos **sin verificar** creados después del 28/07/2020 sólo pueden
  subir videos en modo **`private`** hasta pasar la auditoría de Google. Por
  eso `YOUTUBE_DEFAULT_PRIVACY=private` es el valor por defecto.

### Flujo de publicación que implementa la API

| Paso | Endpoint oficial |
|---|---|
| 1. Iniciar subida resumible | `POST /upload/youtube/v3/videos?uploadType=resumable&part=snippet,status` |
| 2. Subir | `PUT <session_url>` en chunks de 8 MiB con `Content-Range` (308 = continuar) |
| 3. Estado | `GET /youtube/v3/videos?part=status,processingDetails` hasta `processed` |

**Shorts**: no hay endpoint especial. Se sube con el flujo normal y YouTube lo
clasifica como Short si es vertical y dura ≤ 3 minutos.

### Opciones por plataforma

```json
{
  "platform_options": {
    "youtube": {
      "privacy_status": "public",
      "category_id": "22",
      "made_for_kids": false,
      "notify_subscribers": true,
      "publish_at": "2026-10-01T18:00:00Z",
      "contains_synthetic_media": false
    }
  }
}
```

---

## 11. Cómo probar una publicación

```bash
export BASE="http://localhost:8000"          # o la URL de tu Codespace
export API_KEY="$(grep BOOTSTRAP_API_KEYS .env | cut -d= -f2)"
export A="Authorization: Bearer $API_KEY"
```

**1. Comprobar que el servicio está sano**

```bash
curl -s $BASE/health | python -m json.tool
```

**2. Subir el video**

```bash
curl -s -H "$A" -F "file=@mi_video.mp4;type=video/mp4" $BASE/v1/media
# → {"id":"<MEDIA_ID>", "size_bytes":…, "download_url":"…"}
```

**3. Publicar en varias plataformas a la vez**

```bash
curl -s -X POST $BASE/v1/posts \
  -H "$A" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "media_id": "<MEDIA_ID>",
    "caption": "Nuevo video 🔥 #magoosuna",
    "title": "Mi video",
    "description": "Descripción larga para YouTube",
    "tags": ["magoosuna", "reels"],
    "platforms": ["instagram", "tiktok", "youtube"],
    "scheduled_at": null
  }'
```

**4. Consultar el estado**

```bash
curl -s -H "$A" $BASE/v1/posts/<POST_GROUP_ID> | python -m json.tool
```

**5. Programar para más tarde**

```bash
curl -s -X POST $BASE/v1/posts \
  -H "$A" -H "Content-Type: application/json" \
  -d '{
    "media_id": "<MEDIA_ID>",
    "platforms": ["instagram", "tiktok"],
    "scheduled_at": "2026-10-01T18:00:00Z"
  }'
```

**6. Todo en una sola petición (subir + publicar)**

```bash
curl -s -X POST $BASE/v1/posts/upload \
  -H "$A" \
  -F "file=@mi_video.mp4;type=video/mp4" \
  -F "platforms=instagram,tiktok,youtube" \
  -F "caption=Desde una sola llamada"
```

**Sin credenciales de plataforma** puedes probar igualmente: subida,
validación, descarga firmada, autenticación, idempotencia, estados,
programación, cancelación y errores. `make smoke` hace 17 de esas
comprobaciones de golpe.

---

## 12. Integración con Macaly

Guía completa: **[`docs/MACALY.md`](docs/MACALY.md)**. Resumen:

### Base URL

| Entorno | Base URL |
|---|---|
| Codespaces | `https://<tu-codespace>-8000.app.github.dev` |
| Producción | `https://api.tudominio.com` |

Todos los endpoints de negocio van bajo el prefijo **`/v1`**.

### Autenticación

```http
Authorization: Bearer svk_tu_api_key
```

También se acepta `X-API-Key: svk_...`. La key sale de
`BOOTSTRAP_API_KEYS` o de `POST /v1/admin/clients`.

### Cabeceras

| Cabecera | Cuándo | Para qué |
|---|---|---|
| `Authorization: Bearer <key>` | siempre | autenticación |
| `Content-Type: application/json` | cuerpos JSON | — |
| `Idempotency-Key: <uuid>` | `POST /v1/posts` | evitar publicaciones duplicadas |
| `X-Request-ID` | opcional | correlación de logs (se devuelve siempre) |

### Endpoints que usará Macaly

| Método | Ruta | Para qué |
|---|---|---|
| `GET` | `/health` | estado del servicio |
| `GET` | `/v1/platforms` | qué plataformas están configuradas |
| `GET` | `/v1/oauth/{platform}/authorize` | obtener la URL para conectar una cuenta |
| `GET` | `/v1/accounts` | cuentas conectadas |
| `POST` | `/v1/accounts/{id}/refresh` | renovar token manualmente |
| `DELETE` | `/v1/accounts/{id}` | desconectar una cuenta |
| `GET` | `/v1/accounts/{id}/creator-info` | TikTok: privacidad permitida |
| `GET` | `/v1/accounts/{id}/publishing-limit` | Instagram: cuota de 24 h |
| `GET` | `/v1/media/limits` | límites de subida (validar antes de enviar) |
| `POST` | `/v1/media` | subir un video (multipart) |
| `POST` | `/v1/media/from-url` | registrar un video desde una URL |
| `POST` | `/v1/posts` | publicar o programar |
| `POST` | `/v1/posts/upload` | subir y publicar en una llamada |
| `GET` | `/v1/posts` | histórico (filtros y paginación) |
| `GET` | `/v1/posts/{id}` | estado de una publicación |
| `GET` | `/v1/posts/{id}/attempts` | detalle de intentos |
| `POST` | `/v1/posts/{id}/retry` | reintentar un fallo |
| `POST` | `/v1/posts/{id}/cancel` | cancelar pendiente/programada |
| `GET` | `/v1/posts/scheduled/upcoming` | programadas pendientes |

### Ejemplo de request y response

```http
POST /v1/posts HTTP/1.1
Authorization: Bearer svk_tu_api_key
Content-Type: application/json
Idempotency-Key: 8f14e45f-ea0f-4b0e-9f2a-7c1d3e5a9b20

{
  "media_id": "93a19397-0f71-494b-8413-d76c06f7f8d7",
  "caption": "Nuevo reel 🔥",
  "platforms": ["instagram", "tiktok", "youtube"],
  "scheduled_at": null
}
```

```json
HTTP/1.1 201 Created

{
  "id": "9913817b-2ddb-44ba-8322-baa98868e673",
  "status": "queued",
  "media_id": "93a19397-0f71-494b-8413-d76c06f7f8d7",
  "caption": "Nuevo reel 🔥",
  "scheduled_at": null,
  "posts": [
    {
      "id": "574b6edd-9cb2-4655-a327-d55912833598",
      "platform": "instagram",
      "status": "queued",
      "external_post_id": null,
      "external_url": null,
      "attempt_count": 0,
      "error_message": null
    }
  ],
  "skipped_platforms": {}
}
```

### Errores

Todos los errores tienen el mismo formato:

```json
{
  "error": "no_connected_accounts",
  "message": "No hay cuentas conectadas para ninguna de las plataformas solicitadas",
  "details": { "instagram": "No hay ninguna cuenta de instagram conectada…" }
}
```

| HTTP | `error` | Qué hacer |
|---|---|---|
| 401 | `unauthorized` | API key ausente, inválida, revocada o caducada |
| 403 | `forbidden` | token de descarga inválido o caducado |
| 404 | `not_found` | el recurso no existe (o es de otro cliente) |
| 409 | `conflict` | `Idempotency-Key` reutilizada con otro cuerpo |
| 409 | `no_connected_accounts` | conecta la cuenta con `/v1/oauth/...` |
| 409 | `not_cancellable` | ya está publicado o en manos de la plataforma |
| 422 | `validation_error` | el cuerpo no es válido (`details.errors` lo detalla) |
| 422 | `invalid_video` | formato, MIME o tamaño no admitidos |
| 429 | `rate_limited` | respeta `Retry-After` |
| 501 | `not_configured` | falta configurar esa plataforma en el `.env` |
| 502 | `provider_*` | error de la red social (la categoría indica si se reintenta) |

### CORS

Pon el dominio de tu app de Macaly en `CORS_ALLOW_ORIGINS`:

```env
CORS_ALLOW_ORIGINS=https://tu-app.macaly.app
```

---

## 13. Estados, reintentos e idempotencia

### Estados (`GET /v1/posts/{id}`)

```
draft ──► queued ──► uploading ──► processing ──► publishing ──► published
            ▲                                                       
scheduled ──┘                    cualquier estado ──► failed / cancelled
```

| Estado | Significado |
|---|---|
| `draft` | creado, aún sin encolar |
| `queued` | en cola (también mientras espera un reintento) |
| `uploading` | subiendo el video a la plataforma |
| `processing` | la plataforma está procesando el video |
| `scheduled` | esperando su hora de publicación |
| `publishing` | ejecutando la publicación final |
| `published` | publicado (con `external_post_id` y `external_url`) |
| `failed` | agotados los reintentos o error no recuperable |
| `cancelled` | cancelado antes de enviarse a la plataforma |

El estado del **grupo** resume las plataformas: si alguna publicó,
`published`; si todas fallaron, `failed`.

### Idempotencia

Envía `Idempotency-Key` en `POST /v1/posts`:

- misma clave + mismo cuerpo → devuelve **la misma publicación** (no duplica);
- misma clave + cuerpo distinto → **409**;
- si la petición falla, la clave se libera para que puedas reintentar.

### Reintentos

Los errores se clasifican y sólo se reintenta lo que tiene sentido:

| Categoría | ¿Reintenta? | Ejemplo |
|---|---|---|
| `transient` | ✅ | 5xx, timeout, corte de red |
| `rate_limit` | ✅ (espera x4, respeta `Retry-After`) | cuota de la plataforma |
| `processing_timeout` | ✅ | la plataforma tarda demasiado |
| `internal` | ✅ | fallo inesperado nuestro |
| `auth` | ❌ | token caducado → reconectar la cuenta |
| `permanent` | ❌ | la plataforma rechaza definitivamente |
| `configuration` | ❌ | falta una credencial en el `.env` |
| `invalid_video` | ❌ | formato/duración no válidos |

Backoff exponencial con jitter de ±20 %, hasta `MAX_PUBLISH_ATTEMPTS`.
La política vigente se consulta en `GET /v1/posts/config/retries`.

Los reintentos son **reanudables**: el `container_id` de Instagram, el
`publish_id` de TikTok y la `session_url` de YouTube se guardan, así que un
reintento no vuelve a subir el video.

### Webhooks y polling

`GET /v1/webhooks/status` documenta la estrategia real de cada plataforma.
Hoy **ninguna** de las tres ofrece webhooks del estado de publicación, así que
se usa **polling controlado** (mínimo 20 s entre consultas, con tope de
tiempo). El endpoint `POST /v1/webhooks/instagram` está implementado con
verificación `hub.challenge` y validación de firma `X-Hub-Signature-256` para
los eventos que Meta sí envía.

---

## 14. Qué requiere aprobación externa

Esto **no depende del código**: son trámites con cada plataforma.

| Plataforma | Qué hay que conseguir | Sin ello… |
|---|---|---|
| **Instagram** | Cuenta **Professional** (Business/Creator) | no se puede publicar por API |
| **Instagram** | **App Review** de Meta para `instagram_business_content_publish` | sólo funciona con los usuarios de prueba/roles de tu app |
| **TikTok** | Producto **Content Posting API** añadido a la app | no hay endpoints de publicación |
| **TikTok** | Scope **`video.publish`** aprobado | no hay Direct Post |
| **TikTok** | **Audit de la app** ⚠️ | todo lo publicado queda **privado** (`SELF_ONLY`) |
| **TikTok** | **Verificación de dominio** (*URL prefix*) | `PULL_FROM_URL` falla con `url_ownership_unverified` |
| **YouTube** | **Ampliación de cuota** (por defecto ~6 subidas/día) | `quotaExceeded` al superarla |
| **YouTube** | **Auditoría del proyecto** de Google | los videos sólo pueden subirse como `private` |
| **YouTube** | Publicar la app o añadirte como *usuario de prueba* | Google bloquea el consentimiento |
| **Todas** | URL pública **HTTPS** para las Redirect URI | el OAuth no puede completarse |

Todo lo demás está implementado y funcionando.

---

## 15. Trabajar sólo desde el iPad

Guía completa: **[`docs/IPAD.md`](docs/IPAD.md)**. Lo esencial:

1. **Abrir el Codespace**: `github.com/mercadomarcelo5559/magoosuna` →
   `< > Code` → `Codespaces` → crear o pulsar el que ya tengas.
2. **Abrir el terminal**: menú ☰ → *Terminal* → *New Terminal*
   (atajo: `Ctrl` + `` ` `` si tienes teclado).
3. **Arrancar la API**: `make all-in-one`
4. **Abrir Swagger**: pestaña *PORTS* → puerto 8000 → icono del globo 🌐.
   La URL es `https://<tu-codespace>-8000.app.github.dev/docs`.
   > Para que Instagram/TikTok puedan descargar los videos, pon el puerto 8000
   > en **Public**: en *PORTS*, mantén pulsado el 8000 → *Port Visibility* →
   > *Public*.
5. **Detener la API**: `Ctrl+C` en el terminal.
   Y detén el Codespace al terminar (☰ → *Stop Current Codespace*) para no
   gastar cuota.
6. **Guardar cambios**: el editor web guarda automáticamente; con teclado,
   `Cmd+S`.
7. **Commit y push**:
   ```bash
   git add -A
   git commit -m "Describe tu cambio"
   git push
   ```
   O desde el panel *Source Control* (icono de rama): escribe el mensaje →
   ✓ *Commit* → *Sync Changes*.

**No necesitas ningún ordenador encendido**: el Codespace corre en los
servidores de GitHub y el iPad sólo muestra el navegador.

---

## 16. De Codespaces a producción

Guía completa: **[`docs/PRODUCCION.md`](docs/PRODUCCION.md)**.

### Por qué hace falta

| | Codespaces | Producción |
|---|---|---|
| Disponibilidad | sólo mientras está encendido | 24/7 |
| Publicaciones programadas | se ejecutan al reanudar | a su hora exacta |
| Cuota | horas mensuales limitadas | según tu servidor |
| URL | cambia al recrear el Codespace | dominio fijo |
| Coste | **0 €** dentro de la cuota | desde ~5 €/mes |

**Desarrollo gratuito ≠ producción gratuita.** El desarrollo cuesta 0 € extra
usando Codespaces; para producción necesitarás un servidor permanente.

### La migración no cambia la lógica de negocio

Sólo cambian variables de entorno y dónde corren los procesos:

```env
ENVIRONMENT=production
DEBUG=false
LOG_JSON=true

PUBLIC_BASE_URL=https://api.tudominio.com
CORS_ALLOW_ORIGINS=https://tu-app.macaly.app

DATABASE_URL=postgresql+psycopg://usuario:clave@db-interna:5432/social_video_api
REDIS_URL=redis://redis-interno:6379/0

CELERY_TASK_ALWAYS_EAGER=false
SCHEDULER_IN_PROCESS=false        # el barredor pasa a `celery beat`

STORAGE_BACKEND=s3                # Cloudflare R2 o Amazon S3
S3_BUCKET=…
S3_ENDPOINT_URL=…
```

Pasos resumidos:

1. Servidor Linux (VPS) o plataforma con contenedores.
2. `docker compose up -d` (ya incluye api + worker + beat + postgres + redis).
3. Reverse proxy con HTTPS (Caddy o Nginx + Let's Encrypt).
4. Dominio apuntando al servidor.
5. Actualizar las **Redirect URI** en las tres plataformas al nuevo dominio.
6. Object storage (R2/S3) para no guardar videos en el servidor.
7. Copias de seguridad de PostgreSQL y monitorización de `/health`.

### OAuth con URL pública durante el desarrollo

Si necesitas una URL HTTPS estable antes de tener servidor
(**sin** que el sistema dependa de ella):

```bash
# Cloudflare Tunnel, sin cuenta ni configuración
cloudflared tunnel --url http://localhost:8000
# → https://algo-aleatorio.trycloudflare.com
```

Pon esa URL en `PUBLIC_BASE_URL` y regístrala como Redirect URI. La URL de
Codespaces con puerto público suele bastar y es más estable.

---

## 17. Seguridad

Implementado y verificado:

- **Tokens OAuth cifrados** en la base de datos con Fernet
  (AES-128-CBC + HMAC-SHA256). Verificado: en PostgreSQL sólo hay
  `fernet:gAAAAAB…`, nunca el token en claro.
- **API keys hasheadas** (SHA-256 con pepper). El valor en claro sólo se
  muestra una vez, al emitirla. Rotación vía
  `POST /v1/admin/clients/{id}/api-keys/rotate`.
- **Logs sin secretos**: un filtro redacta tokens, `client_secret`,
  cabeceras `Authorization`/`OAuth` y valores `fernet:`. Verificado buscando
  los secretos reales en los logs: 0 apariciones.
- **La API nunca devuelve tokens**, ni siquiera en el `metadata` de las
  cuentas (los tokens de Página de Facebook se filtran de la respuesta).
- **Nunca se almacenan contraseñas** de redes sociales: sólo tokens OAuth.
- **Validación de video** por extensión, MIME declarado **y bytes reales**
  (un `.mp4` falso se rechaza), más límite de tamaño.
- **Path traversal** imposible: nombres de fichero saneados y claves de
  almacenamiento resueltas dentro de la raíz.
- **Aislamiento entre clientes**: cada consulta filtra por `client_id`.
- **`state` de OAuth de un solo uso** y con caducidad (10 min).
- **URLs de descarga firmadas** con HMAC y caducidad, para que las
  plataformas descarguen el video sin exponer la API key.
- **Rate limiting** por API key (Redis, con respaldo en memoria).
- **CORS configurable** por dominio.
- **Webhooks de Meta** con validación de firma `X-Hub-Signature-256`.
- **`.env` en `.gitignore`**; `scripts/check_secrets.sh` (y la CI) buscan
  credenciales hardcodeadas en cada cambio.

```bash
make secrets        # buscar secretos hardcodeados
```

---

## 18. Tests y verificación

```bash
make test           # 251 tests
make test-cov       # con informe de cobertura (85 %)
```

Ningún test publica en una red social de verdad: los providers se sustituyen
por dobles y las llamadas HTTP se simulan con `respx`, comprobando que se
usan los **endpoints oficiales** con los parámetros correctos.

| Fichero | Qué cubre | Tests |
|---|---|---|
| `test_auth.py` | API keys, rate limiting, aislamiento, administración | 15 |
| `test_security.py` | cifrado, firma de URLs, redacción de logs | 19 |
| `test_media.py` | validación, subida, descarga firmada, retención | 25 |
| `test_posts.py` | multiplataforma, estados, idempotencia, scheduling | 33 |
| `test_retries.py` | clasificación de errores, backoff, reanudación | 36 |
| `test_oauth_accounts.py` | flujo OAuth, refresh, desconexión | 32 |
| `test_provider_instagram.py` | endpoints oficiales de Meta | 30 |
| `test_provider_tiktok.py` | endpoints oficiales de TikTok | 30 |
| `test_provider_youtube.py` | endpoints oficiales de YouTube | 31 |

### Verificado ejecutándose (no sólo en tests)

- API arrancada contra **PostgreSQL 16** y **Redis 7** reales
- Migraciones aplicadas, revertidas y reaplicadas (`upgrade` → `downgrade
  base` → `upgrade head`)
- Worker **Celery** conectado, con las 9 tareas registradas, publicando
- Publicación programada despachada por el barredor al llegar su hora
- Llamada **real a la API de Google**: 401 → clasificado como `auth`, con
  fase (`youtube.create_upload_session`), código HTTP y duración registrados
- Cifrado confirmado con `psql` directamente sobre la tabla
- Subida y descarga firmada de un video, comparado byte a byte
- Idempotencia: dos peticiones idénticas → un solo grupo; cuerpo distinto → 409
- `make smoke`: **17/17 comprobaciones correctas**
- Imagen Docker construida y arrancada con healthcheck en verde

---

## Licencia

MIT
