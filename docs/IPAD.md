# Trabajar exclusivamente desde el iPad

No necesitas ningún ordenador encendido. Todo corre en los servidores de
GitHub (Codespaces) y el iPad sólo muestra el navegador.

---

## 1. Abrir el Codespace

1. Abre **Safari** (o Chrome) en el iPad.
2. Ve a `https://github.com/mercadomarcelo5559/magoosuna`
3. Pulsa el botón verde **`< > Code`**.
4. Pestaña **`Codespaces`**:
   - **Primera vez**: `Create codespace on main`.
   - **Siguientes veces**: aparecerá tu Codespace en la lista; púlsalo para
     reanudarlo (conserva todo: ficheros, `.env`, base de datos).
5. La primera creación tarda 2–3 minutos: se instala Python, Docker,
   PostgreSQL, Redis y todas las dependencias, y se genera el `.env` con
   claves nuevas.

### Añádelo a la pantalla de inicio

Con el Codespace abierto: botón **Compartir** → **Añadir a pantalla de
inicio**. Se abrirá como una app, a pantalla completa.

### Consejos para iPad

- **Teclado externo**: muy recomendable (los atajos funcionan con `Cmd`).
- **Sin teclado**: usa siempre los menús; abajo tienes los equivalentes.
- **Modo escritorio**: si algo se ve raro, Safari → `ᴀA` → *Solicitar sitio
  web para ordenador*.
- **Girar a horizontal**: el editor aprovecha mucho mejor el ancho.

---

## 2. Abrir el terminal

**Con menús** (funciona sin teclado):
☰ (arriba a la izquierda) → **Terminal** → **New Terminal**

**Con teclado**: `Ctrl` + `` ` ``

El terminal aparece en la parte inferior. Puedes arrastrar su borde superior
para hacerlo más grande, o usar el icono de maximizar.

Para abrir un segundo terminal (por ejemplo API en uno y worker en otro):
pulsa el **`+`** en la esquina del panel del terminal.

---

## 3. Arrancar la API

En el terminal:

```bash
make all-in-one
```

Eso arranca la API, el worker de publicaciones y el planificador. Verás algo
como:

```
→ Worker de publicaciones (Celery)…
→ API en http://localhost:8000  (Swagger: /docs)
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Si prefieres separarlo en dos terminales

```bash
# Terminal 1
make dev

# Terminal 2 (pulsa + para abrirlo)
make worker
```

### Comprobar que está sana

```bash
make health
```

Debe responder `"status": "ok"`.

---

## 4. Abrir Swagger (la documentación interactiva)

1. En el panel inferior, pestaña **PORTS**.
2. Busca el puerto **8000**.
3. Pulsa el icono del **globo 🌐** (*Open in Browser*).
4. Se abre una pestaña nueva. Añade **`/docs`** al final de la URL:

```
https://<tu-codespace>-8000.app.github.dev/docs
```

Desde ahí puedes probar todos los endpoints sin escribir código: pulsa
*Authorize*, pega tu API key y usa *Try it out*.

### Tu API key

```bash
grep BOOTSTRAP_API_KEYS .env
```

En Swagger, pulsa **Authorize** y pega **sólo la key** (sin la palabra
`Bearer`).

### ⚠️ Poner el puerto en Public (necesario para OAuth)

Para que Instagram, TikTok y YouTube puedan hablar con tu API (callbacks
OAuth y descarga del video), el puerto 8000 debe ser público:

1. Pestaña **PORTS**.
2. Mantén pulsada la fila del puerto **8000**.
3. **Port Visibility** → **Public**.

Comprueba que la URL pública está bien detectada:

```bash
grep PUBLIC_BASE_URL .env
make health          # el componente "public_url" debe estar healthy
```

> Con visibilidad *Private* (la de por defecto) sólo tú puedes acceder, y el
> OAuth de las plataformas fallará.

---

## 5. Detener la API

- **Detener la API**: pulsa `Ctrl` + `C` en el terminal.
  Sin teclado: pulsa el icono de la **papelera 🗑** del panel del terminal
  (cierra el terminal y con él los procesos).
- **Detener PostgreSQL y Redis**: `make down`
- **Detener el Codespace completo** (para no gastar cuota):
  ☰ → **Stop Current Codespace**
  O desde <https://github.com/codespaces>: los tres puntos `⋯` del Codespace →
  **Stop codespace**.

> **Hazlo siempre al terminar.** Un Codespace encendido consume horas de tu
> cuota gratuita aunque no lo estés usando. Detenido, no consume.
> GitHub también lo detiene solo tras 30 minutos de inactividad.

---

## 6. Guardar cambios

El editor web de Codespaces **guarda automáticamente**. Si tienes teclado,
`Cmd` + `S` fuerza el guardado.

Un punto `●` junto al nombre del fichero significa «sin guardar». Suele
desaparecer en un par de segundos.

---

## 7. Commit y push

### Con el terminal

```bash
git status                       # ver qué ha cambiado
git add -A                       # preparar todos los cambios
git commit -m "Describe tu cambio"
git push
```

Ya estás autenticado: Codespaces configura Git con tu cuenta de GitHub, no
tienes que meter contraseña.

### Con la interfaz (sin escribir comandos)

1. Icono de **rama** en la barra lateral izquierda (*Source Control*).
2. Verás la lista de ficheros cambiados.
3. Escribe el mensaje del commit en la caja de arriba.
4. Pulsa **✓ Commit**.
5. Pulsa **Sync Changes** (o *Push*) para subirlo a GitHub.

### Trabajar en la rama de desarrollo

```bash
git branch                                   # en qué rama estás
git checkout claude/social-video-api-cnyi1p  # cambiar a la rama de trabajo
git pull                                     # traer lo último
```

---

## 8. Rutina diaria

```
1. Abrir el Codespace (desde la pantalla de inicio del iPad)
2. ☰ → Terminal → New Terminal
3. make all-in-one
4. PORTS → 8000 → 🌐 → añadir /docs
5. …trabajar…
6. git add -A && git commit -m "…" && git push
7. Ctrl+C  y  ☰ → Stop Current Codespace
```

---

## 9. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| «Address already in use» al arrancar | La API ya está corriendo. `pkill -f uvicorn` y vuelve a intentarlo |
| `make health` dice que la base de datos no responde | `make up` y espera 15 s |
| El OAuth de una plataforma falla con «redirect_uri mismatch» | La Redirect URI del `.env` (`grep REDIRECT_URI .env`) debe coincidir **exactamente** con la registrada en la plataforma. Cambia al recrear el Codespace |
| Instagram no puede descargar el video | Pon el puerto 8000 en **Public** (paso 4) |
| El Codespace va lento | Cierra pestañas del navegador; `make down` si no necesitas PostgreSQL |
| Se me acabó la cuota | Revísala en <https://github.com/settings/billing>. Detén los Codespaces que no uses y borra los antiguos en <https://github.com/codespaces> |
| Perdí el `.env` | `make env && make keys` y pega las claves. **Ojo**: al cambiar `ENCRYPTION_KEY` hay que reconectar las cuentas sociales |
| El terminal se cerró y se paró la API | Normal: los procesos mueren con el terminal. Vuelve a `make all-in-one` |
| Quiero ver qué está pasando | `make logs` (Docker) o mira el terminal donde corre la API |

---

## 10. Lo que NO puedes hacer sólo con el iPad

Para ser honesto sobre los límites:

- **Publicaciones programadas a su hora exacta**: hace falta un servidor
  permanente. En Codespaces se ejecutan cuando enciendes el entorno (no se
  pierde ninguna, pero salen tarde). Ver
  [`PRODUCCION.md`](PRODUCCION.md).
- **Servicio 24/7 para usuarios reales**: mismo motivo.
- Todo lo demás —desarrollar, probar, conectar cuentas, publicar, consultar
  estados, desplegar a producción— se hace desde el navegador del iPad.
