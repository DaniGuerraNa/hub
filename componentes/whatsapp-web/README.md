# Colector de WhatsApp Web (provisional)

Lee la cuenta de WhatsApp de quien usa el hub abriendo el WhatsApp Web real en
un Chromium sin ventana ([whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js)),
y deja cada mensaje como una línea JSON para que la fuente `whatsapp` del
secretario (`src/hub/secretario/fuentes/whatsapp.py`) lo lea. El hub no habla
con WhatsApp: sólo lee los archivos de aquí abajo. El porqué, en la decisión
323 de `ARQUITECTURA.md`.

> 🔴 **Riesgo.** WhatsApp no permite clientes no oficiales y puede bloquear el
> número, temporal o definitivamente, **aunque sólo se lea**. Pruébalo primero
> con un número secundario, exporta antes los chats que te importen y vincula
> una sola vez. Es **provisional**: lo estable sería un colector con whatsmeow
> que escriba el mismo JSONL.

## Los lectores dentro de WhatsApp Web (`lector/`, decisión 331)

Sin sesión propia: `lector/pagina.js` corre dentro del WhatsApp Web que ya
usas y escribe en el mismo `mensajes.jsonl` (con `origen` y `visto`).

| Archivo | Qué es |
|---|---|
| `pagina.js` | El lector: escucha los mensajes nuevos de la página. El mismo en los dos caminos |
| `extension/` | Extensión de Chrome (MV3). Su id es fijo: `extension/ID` |
| `anfitrion.js` | Anfitrión de mensajería nativa: Chrome lo arranca y le pasa lo leído |
| `escritorio.js` | Se engancha por CDP a la app de escritorio (WebView2) e inyecta el lector |
| `escritor.js` | Lo común: escribe la línea, la lista de chats y el latido |
| `instalar.sh` | Desde WSL: `extension`, `escritorio` o `quitar` |

Se prueban en `pruebas/lector.test.js` contra una página que imita a WhatsApp
Web, con Chromium de verdad: la extensión cargada y el anfitrión registrado, y
`escritorio.js` por CDP.

## Sólo lectura

- No llama nunca a `sendMessage`, `sendSeen` ni a nada que escriba (lo vigila
  `tests/test_secretario_whatsapp.py`).
- No abre ningún chat: WhatsApp Web marca leído al abrir un chat en pantalla, y
  aquí sólo se lee su almacén de mensajes.
- Al estar listo llama a `sendPresenceUnavailable()`: no aparece «en línea» y
  el teléfono sigue mostrando sus avisos.
- `takeoverOnConflict: false`: si abres WhatsApp Web en otro navegador, gana el
  tuyo.
- La recogida al arrancar usa `Chat.fetchMessages`, que en whatsapp-web.js
  1.34.7 lee el almacén y, si faltan, llama a `loadEarlierMsgs` (lo mismo que
  subir en un chat). Ninguno de los dos llama a `sendSeen`: no marca leído.
- La multimedia no se descarga: sólo se anota el tipo (y el pie, si lo tiene).

## Instalar

Hace falta Node 22 o más. Para no bajar otro Chromium se usa el que ya instaló
Playwright (`~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome`, el de
número más alto) o el que diga `HUB_WHATSAPP_CHROME`:

```bash
cd componentes/whatsapp-web
PUPPETEER_SKIP_DOWNLOAD=1 npm ci
npm test            # la forma de cada mensaje, sin navegador
```

## Órdenes

Desde la carpeta del hub (pasa el mismo `HUB_HOME` que usa el hub):

```bash
uv run python -m hub.secretario whatsapp comprobar   # hasta el QR, sin vincular nada
uv run python -m hub.secretario whatsapp entrar      # pinta el QR y guarda la sesión
uv run python -m hub.secretario whatsapp escuchar    # proceso largo
```

O directamente `node colector.js entrar | escuchar | comprobar`.

- **`entrar`**: pinta el QR en la terminal. En el teléfono: WhatsApp →
  Dispositivos vinculados → Vincular un dispositivo. Al entrar guarda la lista
  de chats y sale.
- **`escuchar`**: escucha y vuelca. Si se desconecta, reintenta con espera
  creciente (30 s → 10 min). Si WhatsApp cierra la sesión o pide el QR otra
  vez, lo apunta en `estado.json`, lo dice y **para**: reintentar a ciegas una
  sesión cerrada es una señal mala más.
- **`comprobar`**: carga WhatsApp Web con una sesión de usar y tirar, espera al
  QR y sale sin vincular. Sirve para saber si la librería sigue funcionando con
  la versión de hoy de WhatsApp Web.

## Variables

| Variable | Por omisión | Qué es |
|---|---|---|
| `HUB_HOME` | `~/.local/share/hub` | Dónde escribe (`secretario/whatsapp/`) |
| `HUB_SECRETARIO_WHATSAPP` | `~/.secretos/secretario-whatsapp` | La sesión (700). Es la cuenta entera: no se copia ni se comparte |
| `HUB_WHATSAPP_CHROME` | el de Playwright | Ruta del ejecutable de Chromium |
| `HUB_WHATSAPP_AL_ARRANCAR` | `20` | Mensajes por chat que recoge al arrancar de los chats con no leídos o con algo desde el último latido (máx. 40 chats); `0` lo apaga |
| `HUB_WHATSAPP_SIN_SANDBOX` | — | `1` quita el sandbox de Chromium (sólo en contenedores donde no arranca) |

## Lo que escribe

En `HUB_HOME/secretario/whatsapp/` (carpeta 700, archivos 600):

- `mensajes.jsonl`: una línea por mensaje, sólo se añade:
  `{"id", "chat", "chat_nombre", "autor", "autor_id", "de_mi", "texto", "hora"
  (UTC ISO), "grupo", "tipo", "multimedia", "origen" ("vivo" | "arranque")}`.
  Lo del dueño lleva `autor: "Yo"`. Puede repetir un mensaje (recogida y vivo);
  la memoria del secretario lo guarda una vez.
- `chats.json`: la lista de chats (nombre, grupo, no leídos, último), cada 10 min.
- `estado.json`: `{estado, detalle, latido, pid}`, latido cada minuto. Estados:
  `arrancando`, `escuchando`, `reintentando`, `esperando-qr`, `vinculada`,
  `sin-sesion`, `sesion-cerrada`, `parado`.

## Prueba manual hasta el QR (1-nov-2026)

Con `HUB_HOME` y `HUB_SECRETARIO_WHATSAPP` en carpetas temporales, en WSL2,
Node 24.20, whatsapp-web.js 1.34.7 y el Chromium 1248 de Playwright:

1. `node colector.js comprobar` → `WhatsApp Web 2.3000.1052586228 cargó y emitió
   un QR (239 caracteres). No se vincula nada; cerrando.` Sale con 0 en ~3 s,
   sin dejar la carpeta temporal ni procesos de Chromium.
2. `node colector.js entrar`, cortado con Ctrl+C a los 15 s → pinta el QR en la
   terminal y apunta `esperando-qr`; carpetas creadas con 700; sin procesos
   colgados. Nadie lo escaneó.
3. `node colector.js escuchar` sin sesión → `estado.json` con `sin-sesion` y
   sale con 2.

**Sin probar**, porque exige vincular una cuenta: la recepción de mensajes, la
recogida al arrancar, `sendPresenceUnavailable` y la caída por `LOGOUT`.
