# Detalle técnico de cada plataforma

Referencia de los endpoints oficiales que usa la API, los requisitos reales de
cada red social y cómo añadir una plataforma nueva.

Toda la información de esta página se obtuvo de la **documentación oficial
vigente** de cada plataforma, consultada al implementar los providers.

---

## Instagram — Content Publishing API

**Código**: `app/providers/instagram/provider.py`
**Documentación**:
<https://developers.facebook.com/docs/instagram-platform/content-publishing>

### Requisitos de la plataforma

| Requisito | Detalle |
|---|---|
| Tipo de cuenta | **Professional** (Business o Creator). Las personales no publican por API |
| Permisos (Instagram Login) | `instagram_business_basic`, `instagram_business_content_publish` |
| Permisos (Facebook Login) | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`, `pages_show_list` |
| Límite de publicación | **100 posts por API cada 24 h** por cuenta |
| Vida del token | 60 días, renovable sin refresh token |

La API valida el tipo de cuenta al conectar y devuelve un error explicando
cómo cambiarlo si es personal.

### Endpoints usados

| Operación | Método y ruta |
|---|---|
| Diálogo de autorización | `GET https://www.instagram.com/oauth/authorize` |
| Canjear el `code` | `POST https://api.instagram.com/oauth/access_token` |
| Token de 60 días | `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token` |
| Renovar token | `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token` |
| Datos de la cuenta | `GET /v25.0/me?fields=user_id,username,account_type,…` |
| **Crear contenedor** | `POST /v25.0/{ig-user-id}/media` con `media_type=REELS` |
| **Subida resumible** | `POST https://rupload.facebook.com/ig-api-upload/v25.0/{container-id}` |
| **Estado del contenedor** | `GET /v25.0/{container-id}?fields=status_code` |
| **Publicar** | `POST /v25.0/{ig-user-id}/media_publish` con `creation_id` |
| Enlace del post | `GET /v25.0/{media-id}?fields=permalink` |
| Cuota de 24 h | `GET /v25.0/{ig-user-id}/content_publishing_limit` |

Con `INSTAGRAM_LOGIN_MODE=facebook` se usa `graph.facebook.com`, el diálogo
`https://www.facebook.com/v25.0/dialog/oauth`, `grant_type=fb_exchange_token`
y se localiza la cuenta de Instagram a través de
`GET /me/accounts?fields=…,instagram_business_account{id,username}`. En ese
modo se publica con el **token de Página**, no con el del usuario.

### Cabeceras de la subida resumible

```http
POST https://rupload.facebook.com/ig-api-upload/v25.0/{container-id}
Authorization: OAuth {access_token}
offset: 0
file_size: {bytes}

<binario del video>
```

El contenedor debe haberse creado con `upload_type=resumable`.

### Estados del contenedor (`status_code`)

| Valor | Qué hace la API |
|---|---|
| `IN_PROGRESS` | sigue esperando (mínimo 20 s entre consultas) |
| `FINISHED` | publica el contenedor |
| `PUBLISHED` | ya estaba publicado: se considera correcto |
| `ERROR` | error de video → `invalid_video`, no se reintenta |
| `EXPIRED` | contenedor caducado (24 h) → `permanent` |

### Errores de Meta y su clasificación

| Código | Significado | Categoría |
|---|---|---|
| `190`, `102`, `200`, `2500`, `10`, `3` | token/permisos | `auth` (no reintenta) |
| `4`, `17`, `32`, `613`, `80004` | rate limit | `rate_limit` (reintenta, ×4) |
| subcódigos `2207026`, `2207020`, `2207032`, `2207003`, `2207005`, `2207023` | problema con el video | `invalid_video` (no reintenta) |
| `1`, `2` | error interno de la Graph API | `transient` (reintenta) |
| 5xx | caída de Meta | `transient` (reintenta) |
| resto de 4xx | rechazo definitivo | `permanent` |

### Opciones disponibles

```json
{
  "instagram": {
    "media_type": "REELS",
    "cover_url": "https://…/portada.jpg",
    "thumb_offset": 1000,
    "share_to_feed": true,
    "location_id": "123456",
    "collaborators": ["usuario"],
    "audio_name": "Nombre del audio",
    "alt_text": "Texto alternativo"
  }
}
```

---

## TikTok — Content Posting API v2

**Código**: `app/providers/tiktok/provider.py`
**Documentación**:
<https://developers.tiktok.com/doc/content-posting-api-get-started/>

### Requisitos de la plataforma

| Requisito | Detalle |
|---|---|
| Productos en la app | **Login Kit** + **Content Posting API** |
| Scopes | `user.info.basic`, `video.publish` (Direct Post), `video.upload` (inbox) |
| **Audit de la app** | ⚠️ **Sin él, todo lo publicado queda en privado (`SELF_ONLY`)** |
| Verificación de dominio | necesaria para `PULL_FROM_URL` (*URL prefix verification*) |
| Límite | **6 peticiones/minuto** por token en los endpoints de init |
| Vida de los tokens | access 24 h, refresh 365 días |

### Endpoints usados

| Operación | Método y ruta |
|---|---|
| Diálogo de autorización | `GET https://www.tiktok.com/v2/auth/authorize/` |
| Tokens (canje y refresh) | `POST https://open.tiktokapis.com/v2/oauth/token/` |
| Revocar | `POST https://open.tiktokapis.com/v2/oauth/revoke/` |
| **Información del creador** | `POST /v2/post/publish/creator_info/query/` |
| **Init (Direct Post)** | `POST /v2/post/publish/video/init/` |
| **Init (borradores)** | `POST /v2/post/publish/inbox/video/init/` |
| **Subir** | `PUT {upload_url}` con `Content-Range` |
| **Estado** | `POST /v2/post/publish/status/fetch/` |

### Direct Post vs. Inbox

| | `DIRECT_POST` (`video.publish`) | `INBOX` (`video.upload`) |
|---|---|---|
| Qué hace | publica directamente en la cuenta | deja el video en los borradores de la app de TikTok |
| Requiere audit para ser público | sí | el usuario decide al publicar desde la app |
| Metadatos (título, privacidad…) | los envía la API (`post_info`) | los pone el usuario en la app |
| Estado final | `PUBLISH_COMPLETE` | `SEND_TO_USER_INBOX` |

Se elige con `TIKTOK_POST_MODE` o por petición con
`platform_options.tiktok.post_mode`.

### Chunking (reglas implementadas)

| Tamaño del video | `chunk_size` | `total_chunk_count` |
|---|---|---|
| < 64 MB | el tamaño completo | 1 (una sola petición) |
| ≥ 64 MB | 64 MB | `tamaño // 64 MB` — el último chunk absorbe el resto |

Cabeceras de cada `PUT`:

```http
Content-Type: video/mp4
Content-Length: {bytes del chunk}
Content-Range: bytes {primero}-{último}/{total}
```

### Estados (`status`)

| Valor | Qué hace la API |
|---|---|
| `PROCESSING_UPLOAD` / `PROCESSING_DOWNLOAD` | sigue esperando |
| `PUBLISH_COMPLETE` | publicado |
| `SEND_TO_USER_INBOX` | en los borradores del usuario (modo inbox) |
| `FAILED` | según `fail_reason`: `invalid_video` o `permanent` |

### Errores de TikTok y su clasificación

| `error.code` | Categoría |
|---|---|
| `access_token_invalid`, `scope_not_authorized`, `scope_permission_missed`, `token_expired` | `auth` |
| `rate_limit_exceeded`, `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting` | `rate_limit` |
| `file_format_check_failed`, `duration_check_failed`, `frame_rate_check_failed`, `picture_size_check_failed`, `invalid_file_upload`, `invalid_params` | `invalid_video` |
| `privacy_level_option_mismatch`, `url_ownership_unverified`, `publish_attempt_limit_exceeded`, `reached_active_user_cap` | `permanent` |
| `internal_error`, `service_unavailable` | `transient` |

> TikTok puede responder **HTTP 200 con `error.code` distinto de `ok`**. La API
> lo detecta y lo trata como error (hay un test que lo cubre).

### Opciones disponibles

```json
{
  "tiktok": {
    "privacy_level": "PUBLIC_TO_EVERYONE",
    "disable_comment": false,
    "disable_duet": false,
    "disable_stitch": false,
    "video_cover_timestamp_ms": 1000,
    "brand_content_toggle": false,
    "brand_organic_toggle": false,
    "is_aigc": false,
    "post_mode": "DIRECT_POST",
    "duration_seconds": 45
  }
}
```

`privacy_level` debe estar entre los `privacy_level_options` que devuelve
`creator_info`; si no, la API falla con un mensaje explícito **antes** de subir
el video. Usa `GET /v1/accounts/{id}/creator-info` para rellenar el selector.

---

## YouTube — Data API v3

**Código**: `app/providers/youtube/provider.py`
**Documentación**:
<https://developers.google.com/youtube/v3/docs/videos/insert>

### Requisitos de la plataforma

| Requisito | Detalle |
|---|---|
| API habilitada | **YouTube Data API v3** en el proyecto de Google Cloud |
| Tipo de credencial | ID de cliente OAuth de tipo **Aplicación web** |
| Scopes | `youtube.upload`, `youtube.readonly` |
| Parámetros OAuth | `access_type=offline` + `prompt=consent` (para el refresh token) |
| **Cuota** | `videos.insert` cuesta **1600 unidades**; por defecto 10 000/día → ~6 subidas |
| **Auditoría** | Proyectos sin verificar (creados después del 28/07/2020) sólo suben videos `private` |
| Vida de los tokens | access 1 h; refresh sin caducidad (Google no lo rota en cada refresh) |

### Endpoints usados

| Operación | Método y ruta |
|---|---|
| Consentimiento | `GET https://accounts.google.com/o/oauth2/v2/auth` |
| Tokens (canje y refresh) | `POST https://oauth2.googleapis.com/token` |
| Revocar | `POST https://oauth2.googleapis.com/revoke` |
| Datos del canal | `GET /youtube/v3/channels?part=snippet,contentDetails,statistics&mine=true` |
| **Iniciar subida** | `POST /upload/youtube/v3/videos?uploadType=resumable&part=snippet,status` |
| **Subir** | `PUT {session_url}` en chunks de 8 MiB con `Content-Range` |
| **Estado** | `GET /youtube/v3/videos?part=status,processingDetails&id={id}` |

La URL de sesión llega en la cabecera `Location` de la primera respuesta. Un
`308 Resume Incomplete` significa que el chunk se aceptó y hay que continuar.

### Shorts

No existe un endpoint específico. Se sube con el flujo normal y YouTube
clasifica el video como Short si es **vertical** y dura **≤ 3 minutos**.

### Estados (`uploadStatus`)

| Valor | Qué hace la API |
|---|---|
| `uploaded` | sigue esperando el procesado |
| `processed` | publicado correctamente |
| `failed` / `rejected` | `invalid_video` con `failureReason` / `rejectionReason` |
| `deleted` | `permanent` |

### Errores de Google y su clasificación

| `errors[0].reason` | Categoría |
|---|---|
| `quotaExceeded`, `dailyLimitExceeded`, `rateLimitExceeded`, `userRateLimitExceeded`, `uploadLimitExceeded` | `rate_limit` |
| `authError`, `forbidden`, `insufficientPermissions`, `youtubeSignupRequired`, `unauthorized` | `auth` |
| `invalidVideoMetadata`, `mediaBodyRequired`, `invalidVideoTitle`, `invalidDescription`, `invalidTags`, `invalidCategoryId`, `videoTooLong`, `failedPrecondition` | `invalid_video` |
| `backendError`, 5xx | `transient` |
| `invalid_grant` (OAuth) | `auth` — hay que reconectar el canal |

### Límites que aplica la API

- Título: 100 caracteres (se recorta)
- Descripción: 5000 caracteres (se recorta)
- Etiquetas: 500 caracteres en total (se seleccionan las que caben)
- `publish_at` fuerza `privacyStatus=private` hasta esa fecha, como exige la API

### Opciones disponibles

```json
{
  "youtube": {
    "privacy_status": "public",
    "category_id": "22",
    "made_for_kids": false,
    "notify_subscribers": true,
    "embeddable": true,
    "license": "youtube",
    "default_language": "es",
    "publish_at": "2026-10-01T18:00:00Z",
    "contains_synthetic_media": false
  }
}
```

---

## Webhooks: qué ofrece realmente cada plataforma

Consultado en la documentación oficial de las tres:

| Plataforma | ¿Webhook del estado de publicación? | Qué usa la API |
|---|---|---|
| **Instagram** | ❌ Meta tiene webhooks de mensajes, comentarios y menciones, **no** del procesado de un contenedor | polling de `status_code` |
| **TikTok** | ❌ la Content Posting API no ofrece webhooks | polling de `status/fetch/` |
| **YouTube** | ❌ PubSubHubbub avisa de videos nuevos del canal, no del progreso de una subida | polling de `videos.list` |

Por eso se usa **polling controlado**: mínimo 20 s entre consultas
(`PROCESSING_POLL_INTERVAL_SECONDS`, con un suelo de 5 s que no se puede
bajar), con tope de tiempo (`PROCESSING_TIMEOUT_SECONDS`) y una tarea que sólo
revisa los posts realmente atascados (más de 30 min), como máximo 20 por
ejecución.

`POST /v1/webhooks/instagram` está implementado con verificación
`hub.challenge` y validación de firma `X-Hub-Signature-256` para los eventos
que Meta **sí** envía. `GET /v1/webhooks/status` documenta todo esto en
tiempo de ejecución.

Cuando alguna plataforma publique webhooks de estado, sólo hay que añadir el
handler aquí: el resto del sistema ya está preparado
(`publisher.sync_post_status`).

---

## Añadir una plataforma nueva (Facebook, X, LinkedIn…)

La arquitectura está preparada. Son **tres pasos** y no hay que tocar nada más:

### 1. Implementar el provider

`app/providers/linkedin/provider.py`:

```python
from typing import ClassVar

from app.models.enums import Platform
from app.providers.base import (
    AccountInfo, AuthorizationRequest, BaseProvider,
    OAuthCredentials, PublishRequest, PublishResult, RemoteStatus,
)


class LinkedInProvider(BaseProvider):
    platform: ClassVar[Platform] = Platform.LINKEDIN
    setup_docs_url: ClassVar[str] = "https://learn.microsoft.com/linkedin/"

    def is_configured(self) -> bool: ...
    def build_authorization_request(self, *, state, redirect_uri) -> AuthorizationRequest: ...
    def exchange_code(self, *, code, redirect_uri, code_verifier=None) -> OAuthCredentials: ...
    def refresh_token(self, credentials) -> OAuthCredentials: ...
    def get_account(self, credentials) -> AccountInfo: ...
    def publish(self, credentials, request) -> PublishResult: ...
    def get_post_status(self, credentials, external_post_id) -> RemoteStatus: ...
```

Usa `app.utils.http.request` para las llamadas (clasifica errores
automáticamente) y `app.utils.polling.poll_ticks` si hay que esperar un
procesado. Lanza las excepciones de `app.providers.errors` según el tipo de
fallo.

### 2. Registrarlo

`app/providers/registry.py`:

```python
_PROVIDER_CLASSES: dict[Platform, type[BaseProvider]] = {
    Platform.INSTAGRAM: InstagramProvider,
    Platform.TIKTOK: TikTokProvider,
    Platform.YOUTUBE: YouTubeProvider,
    Platform.LINKEDIN: LinkedInProvider,   # ← nuevo
}
```

`Platform.LINKEDIN` ya existe en `app/models/enums.py` (junto con `FACEBOOK` y
`X`), así que no hace falta ninguna migración de base de datos.

### 3. Añadir su configuración

En `app/config.py` y en `.env.example`, siguiendo el patrón de las otras:
`LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REDIRECT_URI`.

### Lo que funciona automáticamente

Sin escribir una línea más:

- `GET /v1/oauth/linkedin/authorize` y `/callback`
- cifrado de tokens y refresh automático antes de publicar
- `POST /v1/posts` con `"platforms": ["linkedin", …]`
- estados, reintentos con backoff, idempotencia, cancelación
- publicaciones programadas
- `GET /v1/platforms` la incluye en el listado
- rate limiting, logs sin secretos, documentación Swagger

### Y añade sus tests

Copia el patrón de `tests/test_provider_youtube.py`: con `respx` se simulan
las respuestas HTTP y se comprueba que se llaman los endpoints oficiales con
los parámetros correctos, sin publicar nada de verdad.
