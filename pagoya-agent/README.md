# Pagoya Agent: adquisición automática de clientes

Este sistema consigue clientes para Pagoya sin que tengas que operarlo cada día. Busca prospectos, los invita por WhatsApp, lleva la conversación con un bot que usa Claude, agenda demos por Zoom y te manda las citas listas. También maneja Instagram y Facebook, anuncios (solo con tu OK), referidos, SEO, la calculadora, Google Business, correo en frío, alianzas y directorios.

## Cómo funciona

```
Google Places ──► CRM (base de datos) ◄── Calculadora / SEO / Referidos / Redes / Anuncios / Correo
                      │
          10:00 y 16:00 lun-vie (60 entregados por turno)
                      ▼
      WhatsApp Cloud API (plantillas aprobadas) ──► prospecto responde ──► Bot (Claude)
                                                         │   pregunta alumnos → precio → demo
                                                         ▼
                                Zoom (link automático) + correo inmediato para ti
                                                         ▼
                                  Resumen diario a las 7:00 pm en tu correo
```

- Todo corre en **un solo servidor**: recibe los webhooks de WhatsApp, Instagram, Facebook y Stripe, y además ejecuta las 19 tareas programadas (hora de Monterrey). Puedes verlas con `python -m pagoya jobs`.
- **GitHub Actions** corre las pruebas en cada cambio y revisa cada 30 min que el servidor siga vivo; si se cae, GitHub te manda un correo.
- La configuración que puedes cambiar sin tocar código vive en `config/settings.yaml`: ciudades, giros, horarios, cuotas, precios y días de publicación.

| Lo que pediste | Dónde quedó |
|---|---|
| Prospección, sin duplicados, solo celulares y formato +52 | `pagoya/places.py`, `pagoya/phones.py` |
| 60 + 60 invitaciones contando solo entregadas, calidad amarillo/rojo | `pagoya/outreach.py` |
| Bot: alumnos antes del precio, tabulador, configuración gratis, demo, BAJA, pasar a humano | `pagoya/bot.py`, `pagoya/pricing.py`, `pagoya/scheduling.py`, `pagoya/zoom.py` |
| CRM con los 8 estados, resumen diario, un solo seguimiento a los 3 días | `pagoya/db.py`, `pagoya/reports.py` |
| Instagram/Facebook: calendario, publicación, DMs, comentarios, spam, quejas, métricas | `pagoya/content.py`, `pagoya/social.py` |
| Anuncios Click-to-WhatsApp, sin gastar sin tu OK | `pagoya/ads.py` |
| Referidos + Stripe | `pagoya/referrals.py` |
| Páginas SEO por giro y ciudad, blog 2 por semana | `pagoya/seo.py`, `site_templates/` |
| Calculadora imán, con contacto en menos de 5 min | `site_templates/calculadora.html`, `/api/lead` |
| Google Business Profile | `pagoya/gbp.py` |
| Correo en frío (50 al día, baja inmediata, 1 seguimiento a los 4 días) | `pagoya/coldemail.py` |
| Alianzas al 20% (con tu aprobación antes de contactar) | `pagoya/partners.py` |
| Directorios | `kit/directorios.md` |
| Panel para leer y responder conversaciones | `/admin`; el link va en cada resumen diario |

---

## Antes de empezar: 3 riesgos que debes conocer

1. **WhatsApp exige consentimiento.** La política de WhatsApp Business pide que la persona haya aceptado recibir mensajes del negocio antes de que le escribas primero. Si invitas a números sacados de Google Maps, Meta puede bajar la calidad del número o bloquearlo. El sistema reduce ese riesgo: usa solo la API oficial, manda pocos mensajes, incluye «BAJA» en cada plantilla, frena a la mitad en amarillo y se pausa solo en rojo. Aun así, empieza con `invitations_per_slot: 20` durante la primera semana y súbelo poco a poco. Los canales con consentimiento (calculadora, anuncios, SEO y referidos) no tienen este riesgo, así que dales prioridad.
2. **REPEP de PROFECO.** Si un número está inscrito en el Registro Público para Evitar Publicidad, no debes mandarle publicidad. Si te registras como proveedor en https://repep.profeco.gob.mx/ y descargas la lista, puedo agregar el filtro.
3. **Celular o fijo.** En México ya no se puede saber por el número si es celular. El sistema usa el Plan de Numeración del IFT si lo descargas (paso 9). Si no lo descargas, WhatsApp avisa cuando un número no tiene cuenta, y ese número se marca y nunca se vuelve a intentar.

---

## Configuración paso a paso

Cada paso termina con el dato que va en tu archivo `.env`. Copia `.env.example` como `.env` y llénalo conforme avances.

### Paso 1. Crea la cuenta del servidor (Render)
1. Crea tu cuenta en https://dashboard.render.com/register y entra con tu GitHub.
2. Ve a https://dashboard.render.com/blueprints, haz clic en **New Blueprint Instance** y elige el repo `magoosuna`. Render lee `pagoya-agent/render.yaml`, que crea el servidor con un disco de 1 GB para la base de datos. El plan Starter cuesta unos US$7 al mes y es necesario porque el plan gratis se apaga y pierde mensajes.
3. Copia la URL que te da Render (algo como `https://pagoya-agent.onrender.com`).
→ `.env`: `PUBLIC_BASE_URL=` esa URL. En `SECRET_KEY=` escribe una frase larga al azar.

### Paso 2. Llave de Claude (cerebro del bot)
1. Entra a https://platform.claude.com/settings/keys y crea una llave.
2. Agrega saldo en https://platform.claude.com/settings/billing.
→ `.env`: `ANTHROPIC_API_KEY=`

### Paso 3. Google Places (prospección)
1. Activa la API en https://console.cloud.google.com/apis/library/places.googleapis.com (si te lo pide, crea un proyecto y agrega una tarjeta en https://console.cloud.google.com/billing).
2. Crea la llave en https://console.cloud.google.com/apis/credentials con **Crear credenciales → Clave de API**.
→ `.env`: `GOOGLE_PLACES_API_KEY=`

### Paso 4. WhatsApp Cloud API (oficial)
1. Crea o abre tu portafolio comercial en https://business.facebook.com/ y verifica tu negocio en https://business.facebook.com/settings/security. Sin esta verificación el límite es de 250 conversaciones al día.
2. Crea una app de tipo **Empresa** en https://developers.facebook.com/apps/creation/ y agrégale el producto **WhatsApp**.
3. En **WhatsApp → Configuración de la API**, agrega el número de Pagoya. Copia el **Phone number ID** y el **WhatsApp Business Account ID**.
4. Crea un token permanente: en https://business.facebook.com/settings/system-users crea un usuario del sistema (Admin), asígnale la app y la cuenta de WhatsApp, y genera un token con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
5. Copia el **App secret** desde **Configuración de la app → Básica**.
6. Agrega un método de pago en el Administrador de WhatsApp: https://business.facebook.com/wa/manage/home/
7. En **WhatsApp → Configuración → Webhook**, pon como URL `PUBLIC_BASE_URL/webhooks/whatsapp`. En «token de verificación» usa la palabra que elijas para `WHATSAPP_VERIFY_TOKEN`. Suscribe los campos `messages`, `phone_number_quality_update` y `account_alerts`.
→ `.env`: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_VERIFY_TOKEN`, `META_APP_SECRET`, `WHATSAPP_PUBLIC_NUMBER` (por ejemplo `528112345678`).

> ¿Quieres seguir usando la app WhatsApp Business en ese número? Al registrarlo en la Cloud API elige la opción de **coexistencia**, que te deja usar la app y la API en el mismo número: https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users

### Paso 5. Manda las plantillas a aprobación
1. En Render abre tu servicio → **Shell** y ejecuta: `python -m pagoya templates`
2. Revisa el estado en https://business.facebook.com/wa/manage/message-templates/. Meta suele aprobarlas entre unos minutos y 24 h. Son: `invitacion_pagoya`, `seguimiento_pagoya`, `resultado_calculadora`, `invita_referidos`, `recordatorio_demo` y `pide_resena` (esta última solo si ya tienes `GOOGLE_REVIEW_LINK`).

### Paso 6. Zoom (links de demo automáticos)
1. Entra a https://marketplace.zoom.us/develop/create y elige **Server-to-Server OAuth App**.
2. Agrega los scopes `meeting:write:meeting:admin` y `user:read:user:admin` y activa la app.
→ `.env`: `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`

### Paso 7. Gmail (resumen diario y avisos)
1. Activa la verificación en 2 pasos: https://myaccount.google.com/signinoptions/twosv
2. Crea una contraseña de aplicación: https://myaccount.google.com/apppasswords
3. Activa IMAP para que pueda leer tus respuestas al calendario: https://mail.google.com/mail/u/0/#settings/fwdandpop
→ `.env`: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `OWNER_EMAIL`

### Paso 8. Prueba con tu número personal (obligatorio antes de lanzar)
Con `TEST_MODE=true`, **todo** mensaje de WhatsApp y todo correo en frío se manda a tu número y a tu correo, nunca a prospectos. Además, los envíos masivos programados (invitaciones, seguimientos, correo en frío y aliados) quedan apagados para que no te lleguen 60 mensajes.
1. Pon tu celular en `OWNER_WHATSAPP=+52...` y deja `TEST_MODE=true`.
2. En el Shell de Render ejecuta: `python -m pagoya test-whatsapp`. Te llega la invitación.
3. Contesta desde tu celular como si fueras una academia. Revisa que el bot pregunte cuántos alumnos tienes antes del precio, que dé el plan correcto, que te ofrezca horarios y que agende la demo con link de Zoom. Te debe llegar un correo «Demo agendada».
4. Escribe «quiero hablar con una persona»: te debe llegar el aviso y el bot se pausa. Escribe «BAJA»: ya no te contesta.
5. Ejecuta `python -m pagoya report` para recibir el resumen diario de prueba.
6. Para probar el bot sin gastar WhatsApp, en tu computadora: `pip install -r requirements.txt && python -m pagoya chat`.
7. Cuando todo esté bien: `TEST_MODE=false` y reinicia el servicio en Render (**Manual Deploy → Restart**).

### Paso 9. Prospección
1. Opcional pero recomendado: descarga el Plan de Numeración del IFT en https://sns.ift.org.mx:8081/sns-frontend/planes-numeracion/descarga-publica.xhtml y guárdalo como `data/ift_numeracion.csv` para descartar teléfonos fijos.
2. La primera vez ejecuta `python -m pagoya prospect`. Para probar solo una ciudad: `python -m pagoya prospect --city "Saltillo, Coahuila"`. Después se ejecuta solo cada domingo de madrugada.
3. Las ciudades y los giros se editan en `config/settings.yaml`.

### Paso 10. Instagram y Facebook
1. Tu cuenta de Instagram debe ser profesional y estar conectada a la página de Facebook de Pagoya: https://www.facebook.com/settings/?tab=linked_instagram
2. En tu app (paso 4) agrega los productos **Facebook Login for Business**, **Instagram** y **Messenger**.
3. Con el usuario del sistema genera un token con estos permisos: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`, `pages_messaging`, `pages_manage_metadata`, `read_insights`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, `instagram_manage_insights`, `ads_management` y `ads_read`. Saca los IDs con https://developers.facebook.com/tools/explorer/ consultando `me/accounts` y `{page-id}?fields=instagram_business_account`.
4. En **Webhooks** de la app, para los objetos **Page** (campos `feed` y `messages`) e **Instagram** (campos `comments` y `messages`), usa la URL `PUBLIC_BASE_URL/webhooks/meta` con tu `META_VERIFY_TOKEN`.
5. Para contestar DMs y comentarios de cualquier persona, la app necesita **Advanced Access** en esos permisos. Pídelo en App Review: https://developers.facebook.com/docs/app-review
6. Graba una sola vez 3 videos verticales de 15 a 30 segundos con la pantalla de la app y súbelos a `media/library/` con estos nombres: `recordatorio_whatsapp.mp4`, `pago_oxxo.mp4` y `panel_dueno.mp4`. Los reels los usan. Mientras no existan, los reels se publican como imagen.
7. Casos de éxito: agrégalos en `config/testimonials.yaml` **solo** con permiso del cliente (`permiso: true`). Si no hay ninguno, el sistema no inventa testimonios.
→ `.env`: `META_PAGE_ID`, `META_PAGE_TOKEN`, `META_IG_USER_ID`, `META_VERIFY_TOKEN`

Cómo funciona: cada domingo a las 10:00 te llega el calendario. Si no respondes con cambios antes del lunes a las 9:00, se publica tal cual. Puedes responder el correo con tus cambios o usar el botón «Pedir cambios»; en ese caso te llega una versión corregida y no se publica nada hasta que la apruebes.

### Paso 11. Anuncios en Meta
1. Copia el ID de tu cuenta publicitaria (sin `act_`) desde https://adsmanager.facebook.com/ y agrega un método de pago en https://business.facebook.com/billing_hub/
2. Para generar una propuesta ejecuta `python -m pagoya ads-propose`; además se genera una sola el día 1 de cada mes. Te llega por correo con presupuesto, segmentación y anuncios. **No se gasta nada hasta que presiones «Aprobar»**.
→ `.env`: `META_AD_ACCOUNT_ID` (y `META_ADS_TOKEN` si usas un token distinto para anuncios)

### Paso 12. Stripe (referidos)
1. Copia la llave secreta desde https://dashboard.stripe.com/apikeys
2. En https://dashboard.stripe.com/webhooks crea un endpoint `PUBLIC_BASE_URL/webhooks/stripe` con los eventos `customer.subscription.created` y `checkout.session.completed`. Copia el **Signing secret**.
3. Guarda el teléfono del cliente en Stripe (o `metadata.whatsapp`): así el sistema lo relaciona con su conversación y sabe quién lo refirió. Si no, en el panel presiona «Marcar como cliente».
→ `.env`: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`

Funcionamiento: cada cliente recibe un link `PUBLIC_BASE_URL/r/CODIGO` que abre WhatsApp con su código. Cuando el referido paga, el nuevo cliente recibe un cupón de 50% en su primer mes y quien lo refirió recibe un crédito igual a su mensualidad. A los 30 días de ser cliente se le invita a referir, y a los 15 días se le pide una reseña.

### Paso 13. Google Business Profile
1. Crea o reclama tu perfil en https://business.google.com/create
2. Pide acceso a la API (es un formulario que tarda unos días): https://developers.google.com/my-business/content/prereqs
3. Crea un cliente OAuth de tipo «Aplicación web» en https://console.cloud.google.com/apis/credentials con el redirect `https://developers.google.com/oauthplayground`.
4. En https://developers.google.com/oauthplayground (engrane → «Use your own OAuth credentials») autoriza el scope `https://www.googleapis.com/auth/business.manage` y copia el **refresh token**.
5. Los IDs de cuenta y ubicación aparecen en la URL de tu perfil, o pídeme que te los saque.
6. Copia tu link para pedir reseñas desde el perfil, en **Pedir reseñas**.
→ `.env`: `GBP_ACCOUNT_ID`, `GBP_LOCATION_ID`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, `GOOGLE_REVIEW_LINK`

Las reseñas de 4 y 5 estrellas se contestan solas. Las de 1 a 3 te llegan con una respuesta propuesta para que la apruebes o la edites.

### Paso 14. Dominio secundario para correo en frío
1. Compra `pagoyamx.com` (o similar), por ejemplo en https://dash.cloudflare.com/?to=/:account/domains/register
2. Crea el buzón `contacto@` en Zoho Mail (gratis, https://www.zoho.com/mail/) o en Google Workspace (https://workspace.google.com/). Configura SPF, DKIM y DMARC con la guía de tu proveedor.
3. **Calienta el dominio**: las primeras 2 semanas pon `cold_email.daily_limit: 10` en `config/settings.yaml` y súbelo poco a poco hasta 50.
→ `.env`: `COLD_SMTP_HOST`, `COLD_IMAP_HOST`, `COLD_EMAIL_USER`, `COLD_EMAIL_PASSWORD`, `BUSINESS_ADDRESS`

### Paso 15. Páginas SEO, blog y calculadora en pagoya.com.mx
1. Para generarlas ejecuta `python -m pagoya site`. Las páginas quedan en `data/site_out/`. Se escriben 2 artículos de blog por semana (martes y jueves) y 40 páginas nuevas en cada corrida.
2. Para publicarlas tienes dos opciones:
   - **Opción A (si tu hosting tiene FTP):** llena `SITE_FTP_HOST`, `SITE_FTP_USER` y `SITE_FTP_PASSWORD` y se suben solas a `pagoya.com.mx/cobranza/...`, `/blog/` y `/calculadora/`.
   - **Opción B (Wix, Shopify, etc.):** crea el subdominio `recursos.pagoya.com.mx` con un CNAME a tu URL de Render, agrégalo en Render en **Settings → Custom Domains**, y pon `SITE_URL=https://recursos.pagoya.com.mx/sitio`.
3. Agrega en el menú de tu sitio el enlace «Calculadora».
4. Da de alta el sitemap (`sitemap-pagoya.xml`) en https://search.google.com/search-console

### Paso 16. Alianzas
Ejecuta `python -m pagoya partners`. El sistema busca contadores, ligas y federaciones, escuelas de entrenadores y proveedores de uniformes, y te manda la propuesta de comisión del 20% del primer año. **No contacta a nadie hasta que la apruebes**. Después escribe a 10 aliados por día, solo a correos públicos.

### Paso 17. Directorios
Sigue `kit/directorios.md`: trae los textos, los precios y los links de alta (Capterra, GetApp, Software Advice, G2, Comparasoftware y otros).

### Paso 18. Vigilancia desde GitHub
En https://github.com/mercadomarcelo5559/magoosuna/settings/variables/actions crea la variable `PAGOYA_URL` con tu `PUBLIC_BASE_URL`. Si el servidor se cae, GitHub te avisa por correo.

### Paso 19. Lanzar
1. `TEST_MODE=false` en Render y reinicia.
2. La primera semana deja `invitations_per_slot: 20` y revisa el resumen de las 7:00 pm. Si la calidad sigue en verde, súbelo a 40 y luego a 60.

---

## Comandos útiles

```
python -m pagoya serve           # servidor + tareas (lo que corre en Render)
python -m pagoya jobs            # lista de tareas y horarios
python -m pagoya run <tarea>     # ejecuta una tarea ya (ej. run invitaciones)
python -m pagoya admin-link      # link privado a tu panel de conversaciones
python -m pagoya quality         # calidad del número de WhatsApp
python -m pagoya report-preview  # guarda el resumen en reporte.html
python -m pytest -q              # pruebas
```

## Reglas que el sistema cumple siempre
- Solo usa la API oficial de WhatsApp y plantillas aprobadas. No automatiza WhatsApp Web.
- Las invitaciones van de lunes a viernes: 60 entregadas a partir de las 10:00 y 60 a partir de las 16:00 (hora de Monterrey). Los intentos fallidos no cuentan como entregados.
- Si la calidad baja a amarillo, el volumen se reduce a la mitad y te avisa. Si baja a rojo, pausa todo, te avisa y espera a que lo reanudes con el link del correo.
- Nunca vuelve a escribir a quien ya fue invitado, es cliente o pidió BAJA (por cualquier canal: WhatsApp, redes o correo).
- Antes de dar cualquier precio pregunta cuántos alumnos tienen. Esto también está bloqueado en el código.
- Las demos se agendan de lunes a sábado de 10:00 a 18:00 (Monterrey), sin empalmes y con al menos 3 h de anticipación.
- Hace un solo seguimiento por WhatsApp (día 3) y uno por correo (día 4). Después deja en paz al prospecto.
- No gasta en anuncios ni contacta aliados sin tu aprobación.
