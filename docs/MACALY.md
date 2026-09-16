# Integración con Macaly

Guía completa para consumir la Social Video API desde una app de Macaly.
Macaly es **sólo el cliente/frontend**: no necesita saber nada de OAuth, de
subidas resumibles ni de reintentos.

---

## 1. Base URL

| Entorno | Base URL |
|---|---|
| Desarrollo (Codespaces) | `https://<tu-codespace>-8000.app.github.dev` |
| Desarrollo (local) | `http://localhost:8000` |
| Producción | `https://api.tudominio.com` |

Todos los endpoints de negocio van bajo **`/v1`**. `/health` y `/docs` están
en la raíz.

Guárdala en Macaly como variable de entorno, p. ej. `SOCIAL_API_BASE_URL`.

---

## 2. Autenticación

Cada petición lleva la API key en la cabecera `Authorization`:

```http
Authorization: Bearer svk_tu_api_key_aqui
```

Alternativa equivalente: `X-API-Key: svk_tu_api_key_aqui`.

### De dónde sale la API key

- **Desarrollo**: del `.env` de la API, variable `BOOTSTRAP_API_KEYS`.
- **Producción**: emítela con el endpoint de administración:

```bash
curl -X POST $BASE/v1/admin/clients \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Macaly", "email": "tu@correo.com"}'
```

```json
{
  "client": { "id": "…", "name": "Macaly", "is_active": true },
  "api_key": "svk_GUARDALA_AHORA_no_se_puede_volver_a_ver"
}
```

**Guarda la key en Macaly como secreto**, nunca en el código del frontend
público. Si Macaly ejecuta código de servidor, úsala desde ahí; si tu app es
puramente de navegador, expón un pequeño proxy en Macaly que añada la
cabecera, para no publicar la key.

### Rotación

```bash
# Listar las keys de un cliente
curl $BASE/v1/admin/clients/{client_id}/api-keys \
  -H "Authorization: Bearer $ADMIN_API_KEY"

# Emitir una nueva y revocar la anterior
curl -X POST $BASE/v1/admin/clients/{client_id}/api-keys/rotate \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"revoke_key_id": "<id_de_la_vieja>", "label": "rotada-2026-10"}'
```

---

## 3. Cabeceras

### Que envía Macaly

| Cabecera | Cuándo | Para qué |
|---|---|---|
| `Authorization: Bearer <key>` | siempre | autenticación |
| `Content-Type: application/json` | cuerpos JSON | — |
| `Content-Type: multipart/form-data` | subida de ficheros | lo pone el navegador |
| `Idempotency-Key: <uuid>` | `POST /v1/posts` | **evitar publicaciones duplicadas** |
| `X-Request-ID: <id>` | opcional | correlacionar con tus logs |

### Que devuelve la API

| Cabecera | Significado |
|---|---|
| `X-Request-ID` | id de la petición (útil para soporte) |
| `X-RateLimit-Limit` | peticiones permitidas por ventana |
| `X-RateLimit-Remaining` | cuántas te quedan |
| `X-RateLimit-Reset` | segundos hasta que se reinicie |
| `Retry-After` | en 429 y en algunos 409: espera esos segundos |

---

## 4. Conectar cuentas de redes sociales

El usuario final conecta su cuenta con un flujo OAuth de dos pasos. Macaly
sólo tiene que **abrir una URL** y esperar a que el usuario vuelva.

### Paso 1 — Macaly pide la URL de autorización

```http
GET /v1/oauth/instagram/authorize?return_url=https://tu-app.macaly.app/cuentas
Authorization: Bearer svk_tu_api_key
```

```json
{
  "platform": "instagram",
  "authorization_url": "https://www.instagram.com/oauth/authorize?client_id=…",
  "state": "3f1c8a…",
  "expires_in": 600
}
```

`platform` puede ser `instagram`, `tiktok` o `youtube`.

### Paso 2 — Macaly abre esa URL en el navegador

```js
window.location.href = data.authorization_url;
// o en una ventana nueva:
window.open(data.authorization_url, "_blank");
```

El usuario acepta en Instagram/TikTok/YouTube. La plataforma redirige a
**nuestra** API (`/v1/oauth/{platform}/callback`), que canjea el `code`,
valida la cuenta y guarda el token **cifrado**.

### Paso 3 — El usuario vuelve a Macaly

Si pasaste `return_url`, la API redirige ahí añadiendo parámetros:

```
https://tu-app.macaly.app/cuentas?status=connected&platform=instagram&account_id=8f2b…
```

Si no pasaste `return_url`, se muestra una página de confirmación sencilla y
el usuario cierra la pestaña.

> Macaly **nunca** ve ni maneja tokens de las redes sociales.

### Listar y gestionar cuentas

```http
GET /v1/accounts                      # todas las activas
GET /v1/accounts?platform=tiktok      # filtradas
GET /v1/accounts/{id}                 # detalle
POST /v1/accounts/{id}/refresh        # renovar token a mano
DELETE /v1/accounts/{id}              # desconectar (revoca y borra tokens)
```

```json
{
  "items": [
    {
      "id": "8f2b1c4e-…",
      "platform": "instagram",
      "account_name": "mi_marca",
      "external_account_id": "17841400000000000",
      "scopes": ["instagram_business_basic", "instagram_business_content_publish"],
      "is_active": true,
      "token_expiration": "2026-11-15T22:00:00Z",
      "has_refresh_token": false,
      "metadata": { "account_type": "BUSINESS", "followers_count": 1234 }
    }
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

La respuesta **nunca incluye tokens**.

### Datos específicos antes de publicar

```http
GET /v1/accounts/{id}/creator-info        # TikTok: privacidad permitida, duración máxima
GET /v1/accounts/{id}/publishing-limit    # Instagram: cuota usada de las últimas 24 h
```

Usa `creator-info` para rellenar el selector de privacidad de TikTok con las
opciones que el creador realmente permite.

---

## 5. Subir el video

### Antes de subir: consulta los límites

```http
GET /v1/media/limits
```

```json
{
  "max_size_mb": 512,
  "allowed_mime_types": ["video/mp4", "video/quicktime", "video/webm"],
  "allowed_extensions": [".mov", ".mp4", ".webm"],
  "retention_hours": 24,
  "storage_backend": "local",
  "public_url_reachable": true
}
```

Valida en el cliente con esos valores para no gastar ancho de banda.

> Si `public_url_reachable` es `false`, Instagram no podrá descargar el video
> (la API lo suplirá con subida resumible, pero conviene avisar al operador).

### Opción A — Subir el fichero

```js
const fd = new FormData();
fd.append("file", archivo);          // input type="file"

const r = await fetch(`${BASE}/v1/media`, {
  method: "POST",
  headers: { Authorization: `Bearer ${API_KEY}` },  // NO pongas Content-Type
  body: fd,
});
const media = await r.json();        // media.id  ← guárdalo
```

```json
{
  "id": "93a19397-0f71-494b-8413-d76c06f7f8d7",
  "status": "ready",
  "filename": "reel.mp4",
  "content_type": "video/mp4",
  "size_bytes": 5242880,
  "checksum_sha256": "a03543…",
  "expires_at": "2026-09-17T22:23:09Z",
  "download_url": "https://…/v1/media/93a1…/download?token=…"
}
```

### Opción B — Registrar el video desde una URL

```http
POST /v1/media/from-url
Content-Type: application/json

{ "video_url": "https://cdn.tu-cdn.com/videos/reel.mp4", "download": true }
```

Con `download: true` (recomendado) la API descarga y valida el fichero; es
necesario para YouTube, que no acepta publicar desde URL.

### Retención

Los videos se borran automáticamente pasadas `MEDIA_RETENTION_HOURS` (24 por
defecto), salvo que tengan publicaciones en curso. Para borrar antes:

```http
DELETE /v1/media/{id}
```

---

## 6. Publicar

### Publicación inmediata y multiplataforma

```http
POST /v1/posts
Authorization: Bearer svk_tu_api_key
Content-Type: application/json
Idempotency-Key: 8f14e45f-ea0f-4b0e-9f2a-7c1d3e5a9b20

{
  "media_id": "93a19397-0f71-494b-8413-d76c06f7f8d7",
  "caption": "Nuevo reel 🔥 #magoosuna",
  "title": "Mi video",
  "description": "Descripción larga (la usa YouTube)",
  "tags": ["magoosuna", "reels"],
  "platforms": ["instagram", "tiktok", "youtube"],
  "scheduled_at": null,
  "platform_options": {
    "youtube": { "privacy_status": "public", "category_id": "22" },
    "tiktok":  { "privacy_level": "PUBLIC_TO_EVERYONE", "disable_comment": false },
    "instagram": { "media_type": "REELS" }
  }
}
```

**201 Created**

```json
{
  "id": "9913817b-2ddb-44ba-8322-baa98868e673",
  "status": "queued",
  "media_id": "93a19397-…",
  "caption": "Nuevo reel 🔥 #magoosuna",
  "scheduled_at": null,
  "posts": [
    {
      "id": "574b6edd-…",
      "platform": "instagram",
      "status": "queued",
      "social_account_id": "8f2b1c4e-…",
      "external_post_id": null,
      "external_url": null,
      "attempt_count": 0,
      "error_message": null
    },
    { "id": "…", "platform": "tiktok",  "status": "queued", "…": "…" },
    { "id": "…", "platform": "youtube", "status": "queued", "…": "…" }
  ],
  "skipped_platforms": {}
}
```

Guarda `id` (el grupo) para consultar el estado.

### Qué campo usa cada plataforma

| Campo | Instagram | TikTok | YouTube |
|---|---|---|---|
| `caption` | pie del Reel | título del video | descripción (si falta `description`) |
| `title` | — | — | título del video |
| `description` | — | — | descripción |
| `tags` | — | se toman del `caption` | etiquetas del video |

Lo práctico: rellena `caption` siempre, y `title`/`description` si publicas en
YouTube.

### Una plataforma sin cuenta no bloquea a las demás

Si pides 3 plataformas y sólo 2 tienen cuenta conectada, se publica en esas 2
y las otras se listan en `skipped_platforms`:

```json
{
  "posts": [ { "platform": "instagram", "…": "…" } ],
  "skipped_platforms": {
    "tiktok": "No hay ninguna cuenta de tiktok conectada. Conéctala con GET /v1/oauth/tiktok/authorize"
  }
}
```

Si **ninguna** tiene cuenta, la respuesta es **409** con `error:
"no_connected_accounts"`.

Lo mismo con los fallos: si TikTok rechaza el video, Instagram y YouTube
siguen publicándose; ese post concreto queda en `failed` con su
`error_message`.

### Subir y publicar en una sola llamada

```js
const fd = new FormData();
fd.append("file", archivo);
fd.append("platforms", "instagram,tiktok,youtube");
fd.append("caption", "Desde una sola llamada");
fd.append("tags", "magoosuna,reels");
// opcional: fd.append("scheduled_at", "2026-10-01T18:00:00Z");

await fetch(`${BASE}/v1/posts/upload`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${API_KEY}`,
    "Idempotency-Key": crypto.randomUUID(),
  },
  body: fd,
});
```

---

## 7. Programar publicaciones

```http
POST /v1/posts
Content-Type: application/json

{
  "media_id": "93a19397-…",
  "platforms": ["instagram", "tiktok"],
  "caption": "Se publica el 1 de octubre",
  "scheduled_at": "2026-10-01T18:00:00Z"
}
```

- `scheduled_at` en **ISO-8601**, con `Z` (UTC) o con offset (`+02:00`).
- Debe ser una fecha **futura**; si no, **422**.
- El grupo y sus posts quedan en estado `scheduled`.

```http
GET /v1/posts/scheduled/upcoming      # programadas pendientes
POST /v1/posts/{id}/cancel            # cancelar antes de que se publique
```

> ⚠️ **Avisa a tus usuarios**: mientras la API corra en Codespaces, las
> publicaciones programadas se ejecutan sólo cuando el entorno está
> encendido. Nada se pierde (al arrancar se recupera todo lo vencido), pero no
> salen a su hora exacta. Para eso hace falta un servidor permanente.

---

## 8. Consultar el estado

```http
GET /v1/posts/{id}                # id del grupo o de un post individual
GET /v1/posts/{id}?sync=true      # además consulta a la plataforma
GET /v1/posts/{id}/status         # alias que siempre sincroniza
```

```json
{
  "id": "9913817b-…",
  "status": "published",
  "posts": [
    {
      "id": "574b6edd-…",
      "platform": "instagram",
      "status": "published",
      "external_post_id": "17999000000000000",
      "external_url": "https://www.instagram.com/reel/ABC123/",
      "published_at": "2026-09-16T22:26:41Z",
      "attempt_count": 1,
      "error_message": null,
      "attempts": [
        {
          "attempt_number": 1,
          "status": "succeeded",
          "stage": "published",
          "duration_ms": 8421,
          "started_at": "2026-09-16T22:26:33Z",
          "finished_at": "2026-09-16T22:26:41Z"
        }
      ]
    }
  ]
}
```

### Estados

| Estado | Qué mostrar en la interfaz |
|---|---|
| `draft` | «Borrador» |
| `queued` | «En cola» (también mientras espera un reintento) |
| `uploading` | «Subiendo…» |
| `processing` | «La plataforma está procesando el video…» |
| `scheduled` | «Programada para {fecha}» |
| `publishing` | «Publicando…» |
| `published` | «Publicado» + enlace a `external_url` |
| `failed` | «Error» + `error_message` + botón de reintentar |
| `cancelled` | «Cancelada» |

### Cada cuánto consultar

Sugerencia para la interfaz: cada **5 s** mientras haya posts en estado
activo (`queued`, `uploading`, `processing`, `publishing`), y deja de
consultar cuando todos estén en un estado final. Respeta los límites:
`X-RateLimit-Remaining` te dice cuánto margen tienes.

### Histórico

```http
GET /v1/posts?limit=20&offset=0
GET /v1/posts?platform=instagram
GET /v1/posts?status=failed
```

```json
{ "items": [ … ], "total": 57, "limit": 20, "offset": 0 }
```

### Reintentar y cancelar

```http
POST /v1/posts/{post_id}/retry     # sólo posts en failed/cancelled/queued
POST /v1/posts/{id}/cancel         # sólo si aún no se envió a la plataforma
GET  /v1/posts/{id}/attempts       # historial detallado de intentos
```

---

## 9. Idempotencia (importante)

Envía siempre `Idempotency-Key` en `POST /v1/posts` y `POST /v1/posts/upload`.
Así, si el usuario pulsa dos veces o la red falla y reintentas, **no se
publica dos veces**.

```js
// Genera la clave UNA vez por intención de publicar y reutilízala en los reintentos
const idempotencyKey = crypto.randomUUID();

async function publicar(cuerpo) {
  return fetch(`${BASE}/v1/posts`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,   // la MISMA en cada reintento
    },
    body: JSON.stringify(cuerpo),
  });
}
```

Comportamiento:

| Situación | Respuesta |
|---|---|
| Misma clave, mismo cuerpo | **201** con la publicación original (no duplica) |
| Misma clave, cuerpo distinto | **409** `conflict` |
| Solicitud original aún en curso | **409** con `Retry-After: 5` |
| La solicitud falló | la clave se libera: puedes reintentar con ella |

---

## 10. Errores

Formato único para todos los errores:

```json
{
  "error": "codigo_estable",
  "message": "Explicación legible",
  "details": { "…": "contexto opcional" }
}
```

Programa contra `error` (es estable); muestra `message` al usuario.

| HTTP | `error` | Qué significa / qué hacer |
|---|---|---|
| 401 | `unauthorized` | API key ausente, inválida, revocada o caducada |
| 403 | `forbidden` | token de descarga de media inválido o caducado |
| 404 | `not_found` | no existe (o pertenece a otro cliente) |
| 409 | `conflict` | `Idempotency-Key` reutilizada con otro cuerpo |
| 409 | `no_connected_accounts` | conecta la cuenta con `/v1/oauth/{platform}/authorize` |
| 409 | `not_cancellable` | ya publicado o en manos de la plataforma |
| 422 | `validation_error` | cuerpo inválido; `details.errors[]` indica campo y motivo |
| 422 | `invalid_video` | formato, MIME o tamaño no admitidos |
| 429 | `rate_limited` | espera lo que diga `Retry-After` |
| 501 | `not_configured` | esa plataforma no tiene credenciales en el `.env` |
| 502 | `provider_transient` | fallo temporal de la red social (la API ya reintenta) |
| 502 | `provider_permanent` | la red social rechazó la publicación |
| 401 | `provider_auth` | el token de la cuenta ya no vale: hay que reconectarla |
| 429 | `provider_rate_limit` | límite de la red social |
| 500 | `internal_error` | error nuestro; el `X-Request-ID` ayuda a diagnosticarlo |

Ejemplo de error de validación:

```json
{
  "error": "validation_error",
  "message": "La petición no es válida",
  "details": {
    "errors": [
      {
        "field": "body",
        "message": "Value error, Indica exactamente uno de `media_id` o `video_url`",
        "type": "value_error"
      }
    ]
  }
}
```

---

## 11. CORS

Si Macaly llama a la API **directamente desde el navegador**, añade su dominio
en el `.env` de la API:

```env
CORS_ALLOW_ORIGINS=https://tu-app.macaly.app,https://otro-dominio.com
```

Cabeceras permitidas: `Authorization`, `Content-Type`, `Idempotency-Key`,
`X-API-Key`. Cabeceras expuestas: `X-Request-ID` y las de rate limit.

> Si puedes, llama a la API desde el **servidor** de Macaly en lugar del
> navegador: así la API key no viaja al cliente.

---

## 12. Ejemplo completo en JavaScript

```js
const BASE = process.env.SOCIAL_API_BASE_URL;
const API_KEY = process.env.SOCIAL_API_KEY;          // secreto del servidor

const cabeceras = (extra = {}) => ({
  Authorization: `Bearer ${API_KEY}`,
  ...extra,
});

async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(`${BASE}${ruta}`, opciones);
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    const error = new Error(cuerpo.message || respuesta.statusText);
    error.codigo = cuerpo.error;
    error.estado = respuesta.status;
    error.detalles = cuerpo.details;
    error.requestId = respuesta.headers.get("X-Request-ID");
    throw error;
  }
  return cuerpo;
}

// 1. ¿Qué plataformas están listas?
const plataformas = await pedir("/v1/platforms", { headers: cabeceras() });

// 2. Conectar una cuenta
const { authorization_url } = await pedir(
  "/v1/oauth/instagram/authorize?return_url=https://tu-app.macaly.app/cuentas",
  { headers: cabeceras() },
);
// → abre authorization_url en el navegador del usuario

// 3. Subir el video
const fd = new FormData();
fd.append("file", archivo);
const media = await pedir("/v1/media", {
  method: "POST",
  headers: cabeceras(),        // sin Content-Type: lo pone FormData
  body: fd,
});

// 4. Publicar
const clave = crypto.randomUUID();
const grupo = await pedir("/v1/posts", {
  method: "POST",
  headers: cabeceras({
    "Content-Type": "application/json",
    "Idempotency-Key": clave,
  }),
  body: JSON.stringify({
    media_id: media.id,
    caption: "Nuevo reel 🔥",
    title: "Mi video",
    description: "Descripción para YouTube",
    platforms: ["instagram", "tiktok", "youtube"],
    scheduled_at: null,
  }),
});

// 5. Seguir el estado hasta que todos terminen
const ACTIVOS = ["queued", "uploading", "processing", "publishing"];

async function seguir(grupoId, alActualizar) {
  for (;;) {
    const estado = await pedir(`/v1/posts/${grupoId}`, { headers: cabeceras() });
    alActualizar(estado);
    if (!estado.posts.some((p) => ACTIVOS.includes(p.status))) return estado;
    await new Promise((r) => setTimeout(r, 5000));
  }
}

const final = await seguir(grupo.id, (e) => console.log(e.status));
for (const p of final.posts) {
  console.log(p.platform, p.status, p.external_url ?? p.error_message);
}
```

---

## 13. Lista de comprobación para Macaly

- [ ] `SOCIAL_API_BASE_URL` y `SOCIAL_API_KEY` configuradas como secretos
- [ ] La API key **no** aparece en el código del navegador
- [ ] `CORS_ALLOW_ORIGINS` incluye el dominio de la app (si llamas desde el navegador)
- [ ] Se envía `Idempotency-Key` en cada publicación
- [ ] Se validan tamaño y formato con `GET /v1/media/limits` antes de subir
- [ ] Se muestran los 9 estados y el botón de reintentar en `failed`
- [ ] Se muestran las plataformas de `skipped_platforms` como «no conectada»
- [ ] Se usa `creator-info` para el selector de privacidad de TikTok
- [ ] Se avisa de que las publicaciones programadas necesitan la API encendida
- [ ] Se guarda `X-Request-ID` en los logs para soporte
