# El protocolo del JetKVM, sacado de su código

Todo lo de aquí está **leído del código del firmware** (`github.com/jetkvm/kvm`)
salvo lo marcado **NO VERIFICADO**. Nada se ha visto todavía con un aparato
delante: «leído del código» quiere decir que el código dice eso, no que se haya
medido. Lo que el cliente del puente (`src/puente_kvm/jetkvm.py`) usa de todo
esto está marcado con ▸.

## Versiones contrastadas (13-nov-2026)

El repositorio publica las versiones como etiquetas `release/X.Y.Z`; la rama
`main` está parada en 0.4.8 (2025) y no cuenta.

| Versión | Dónde | Commit | Fecha |
|---|---|---|---|
| 0.5.9 | etiqueta `release/0.5.9` | `36c008f` | 2026-09-08 |
| **0.5.10, la última estable** | etiqueta `release/0.5.10` | `f152581` | 2026-10-30 |
| 0.5.11, sin publicar | rama `dev` | `e9d88d4` (lectura original) → `dba810d` | 2026-11-03 → 11-11 |

La primera versión de este documento se escribió leyendo `dev` en `e9d88d4`
(«chore: bump to 0.5.11»), y sus números de línea son de ese commit. **No
existe una etiqueta 0.5.11**: lo que tendrá un aparato al día es la 0.5.10.

**Lo que usa el cliente es igual en las tres.** Comparados `web.go`,
`webrtc.go`, `cloud.go`, `jsonrpc.go`, `usb.go`, `hidrpc.go`,
`internal/hidrpc/`, `internal/usbgadget/hid_keyboard.go` y
`hid_mouse_absolute.go`:

- 0.5.9 → 0.5.10: ningún cambio en esos archivos.
- 0.5.10 → 0.5.11 (dev): nada que toque al cliente. Lo nuevo de dev: `sku` en
  `/device/status`; al abrirse el canal `rpc` manda `localVersion` y
  `deviceCapabilities` sin que se pidan; los métodos `getDeviceCapabilities` y
  `setVideoStreamPaused`; la ruta de los dispositivos HID se resuelve por
  nombre (`hidDevicePath`) y un intento de recuperar la enumeración USB. En
  0.5.10 nada de eso existe, y el cliente no lo necesita.
- 0.5.8: ya tiene la señalización por WebSocket, `device-metadata` y HID-RPC,
  pero su `webrtc.go` cambia mucho hacia 0.5.9 y no se ha comparado línea a
  línea. Queda **fuera de lo contrastado**.

El cliente dice qué firmware ve (`estado()` → `firmware`,
`firmware_contrastado`) y, si no es 0.5.9, 0.5.10 ni 0.5.11, lo apunta en la
bitácora como aviso (`jetkvm.FIRMWARE_CONTRASTADO`). `puente-kvm comprobar`
también lo dice.

---

## a. Inicio de sesión (acceso local)

Servidor HTTP: gin en el puerto 80, siempre (`web.go`, `main.go`). HTTPS en el
443 sólo si se activa TLS en los ajustes del aparato. El aparato no comprueba
`Origin` ni CSRF.

| Ruta | Acceso | Cuerpo / respuesta |
|---|---|---|
| `GET /device/status` | pública, CORS `*` | → `{"isSetup": bool}` (en 0.5.11 además `"sku"`). `isSetup = LocalAuthMode != ""` |
| ▸ `GET /device` | protegida | → `{"authMode": "password"\|"noPassword", "deviceId", "loopbackOnly"}`; **401 `{"error":"Unauthorized"}`** sin cookie válida: es la pregunta «¿estoy dentro?» que hace su web |
| ▸ `POST /auth/login-local` | pública | `{"password":"…"}` → 200 + `Set-Cookie: authToken=<uuid>; Path=/; Max-Age=604800; HttpOnly`. 401 contraseña mala; 400 en modo sin contraseña; 429 + `Retry-After` (límite por IP) |
| `POST /auth/logout` | protegida | borra el token |
| `POST /device/setup` | pública, sólo sin configurar | `{"localAuthMode":"password"\|"noPassword","password":"…"}` |
| `GET /metrics` | **pública** | métricas de Prometheus |

El modo lo decide `config.LocalAuthMode` (`""` sin configurar, `"password"`,
`"noPassword"`), elegido la primera vez. En `noPassword` todo pasa sin cookie;
si no, la cookie `authToken` tiene que ser `config.LocalAuthToken`.

- 🔴 **Hay UN solo token válido.** Cada inicio de sesión hace
  `config.LocalAuthToken = uuid.New()`: entrar desde el puente echa a un
  navegador que tuviera la web del JetKVM abierta (en su siguiente petición
  protegida) y al revés. El token no caduca por tiempo; la cookie, a los 7 días.
  El puente no guarda la cookie en disco (es una llave) y entra en cada conexión.
- Con aiohttp hace falta `CookieJar(unsafe=True)`: el tarro por omisión tira las
  cookies que pone un host que es una IP.

## b. Señalización WebRTC

▸ **Sólo por WebSocket**: `GET /webrtc/signaling/client` (grupo protegido: la
cookie tiene que ir en la petición de *upgrade*). No comprueba `Origin`.
`POST /webrtc/session` existió hasta 0.5.8 y se quitó en 0.5.9.

Mensajes, todos de texto, JSON `{"type": …, "data": …}`:

1. ▸ Aparato → cliente nada más aceptar:
   `{"type":"device-metadata","data":{"deviceVersion":"0.5.10"}}`. Es de donde
   el puente saca la versión. Su web no crea la conexión WebRTC hasta recibirlo.
2. ▸ **La oferta la hace el cliente**:
   `{"type":"offer","data":{"sd": base64(JSON({"type":"offer","sdp":"v=0…"}))}}`.
   El aparato la decodifica con `base64.StdEncoding` y la lee como
   `webrtc.SessionDescription`.
3. ▸ Aparato → cliente, la respuesta, también en base64 del JSON:
   `{"type":"answer","data":"eyJ0eXBlIjoiYW5zd2VyIi…"}`. Los errores llegan como
   `{"error": …}` sin `type`.
4. ▸ **ICE por goteo, en los dos sentidos**, tipo `new-ice-candidate`, con
   `data` = `ICECandidateInit` de pion
   (`{"candidate":"candidate:…","sdpMid":"…","sdpMLineIndex":N,"usernameFragment":null}`).
   Pueden llegar **antes** que la respuesta (el aparato empieza a reunirlos en
   `SetLocalDescription` y escribe la respuesta después): se guardan y se añaden
   tras `setRemoteDescription`. El aparato nunca manda el fin de candidatos.
   aiortc reúne los suyos antes de terminar `setLocalDescription` y los mete en
   la oferta, así que mandarlos aparte es opcional.
5. Latido: el aparato manda *Ping* del protocolo WebSocket cada 15 s (aiohttp
   contesta solo). El cliente puede mandar el texto `ping` y recibe `pong`.
6. Sin servidores ICE en sesiones locales; mDNS sólo pregunta o está apagado.

**Una sola sesión.** Al aceptar una oferta nueva con una sesión ya abierta, la
vieja recibe el evento JSON-RPC ▸ `otherSessionConnected`, se le sueltan las
teclas y su conexión se cierra 1 s después (`cloud.go`, igual en 0.5.10 y
0.5.11). Su web no se reconecta sola: espera a que alguien pulse «Use Here».
El puente lo dice en el estado y tampoco se reconecta solo.

La conexión WebRTC no depende del WebSocket: si se cierra, nada cierra la
conexión, pero los candidatos que llegaran después se pierden. El puente
mantiene el WebSocket abierto mientras dura la sesión.

### Qué lleva la oferta (`ui/src/routes/devices.$id.tsx`)

```js
pc.addTransceiver("video", { direction: "recvonly" });
pc.addTransceiver("audio", { direction: "recvonly" });          // opcional
const rpc = pc.createDataChannel("rpc");                        // fiable, ordenado
const hid = pc.createDataChannel("hidrpc");                     // fiable, ordenado, binario
pc.createDataChannel("hidrpc-unreliable-ordered",   { ordered: true,  maxRetransmits: 0 });
pc.createDataChannel("hidrpc-unreliable-nonordered",{ ordered: false, maxRetransmits: 0 });
```

- ▸ Vídeo: el aparato añade su pista antes de `SetRemoteDescription` y
  contesta a una línea de vídeo `recvonly`.
- ▸ **Sin audio**: el aparato sólo añade audio si la oferta trae `G722/8000` o
  `PCMU/8000` y el audio está activo; aiortc ofrece PCMU, así que con un
  transceptor de audio el aparato se pondría a capturarlo para nada.
- ▸ Códec: H.265 sólo si la oferta contiene `H265` y la preferencia es
  `auto`/`h265`; si no, H.264. El puente ofrece sólo H.264.
- ▸ aiortc con `RTCConfiguration(iceServers=[])`: sin eso añade un STUN de
  Google y, en una red sin internet, se queda esperando.

## c. Canales de datos

Los crea **el cliente**; el aparato reacciona en `OnDataChannel` según la etiqueta.

| Etiqueta | Opciones | Contenido | Uso en el aparato |
|---|---|---|---|
| ▸ `rpc` | fiable, ordenado | JSON-RPC 2.0 en texto | todo el RPC. Al abrirse empuja `otaState`, `videoInputState`, `usbState`… (y en 0.5.11, además, `localVersion` y `deviceCapabilities`) |
| ▸ `hidrpc` | fiable, ordenado | **binario** | saludo, teclado, macros, cambios de botón del ratón; el aparato manda sus informes **sólo** por éste |
| ▸ `hidrpc-unreliable-ordered` | `ordered:true, maxRetransmits:0` | binario | movimientos del ratón sin cambio de botón |
| `hidrpc-unreliable-nonordered` | `ordered:false, maxRetransmits:0` | binario | aceptado; su web casi no lo usa |
| `terminal`, `serial`, `cdcacm` | opcionales | crudo | consola, puerto serie, USB CDC-ACM |
| `upload_<id>` | opcional | binario | subir imágenes para el medio virtual |

▸ Los canales HID **rechazan mensajes de texto**: en aiortc se manda `bytes`.

### JSON-RPC 2.0 por `rpc`

```json
→ {"jsonrpc":"2.0","method":"getVideoState","params":{},"id":1}
← {"jsonrpc":"2.0","result":{"ready":true,"streaming":1,"width":1920,"height":1080,"fps":60},"id":1}
← {"jsonrpc":"2.0","id":2}                                  (método sin resultado: no lleva "result")
← {"jsonrpc":"2.0","error":{"code":-32601,"message":"Method not found"},"id":3}
← {"jsonrpc":"2.0","method":"videoInputState","params":{…}}        (evento: sin id)
```

- `params` es **un objeto con nombres** (los de `rpcHandlers`); los números
  llegan como float64 y se convierten; una lista de números pasa a `[]byte`.
- ▸ **Las llamadas JSON-RPC se atienden en paralelo** (`go onRPCMessage`): dos
  `keyboardReport` seguidos pueden aplicarse desordenados. El puente espera la
  respuesta de cada una, y el teclado va por HID-RPC, que tiene colas
  ordenadas por tipo.
- Eventos del aparato: `atxState, dcState, deviceCapabilities, failsafeMode,
  keyboardLedState, keyboardMacroState, keysDownState, localVersion,
  networkState, otaProgress, otaState, otherSessionConnected, usbState,
  videoInputState, willReboot`. Los tres de teclado van por JSON-RPC sólo hasta
  el saludo HID; después llegan en binario por `hidrpc`.

## d. Teclado

Códigos **USB HID, página 0x07** (`KeyA`=0x04 … `KeyZ`=0x1d, `Digit1`=0x1e …
`Digit0`=0x27, `Enter`=0x28, `Escape`=0x29, `Backspace`=0x2a, `Tab`=0x2b,
`Space`=0x2c, `F1`=0x3a…, flechas 0x4f–0x52, `Delete`=0x4c,
`IntlBackslash`=0x64…).

Modificadores:

| bit | LCtrl | LShift | LAlt | LMeta | RCtrl | RShift | RAlt/AltGr | RMeta |
|---|---|---|---|---|---|---|---|---|
| máscara | 0x01 | 0x02 | 0x04 | 0x08 | 0x10 | 0x20 | 0x40 | 0x80 |

Informe de arranque: 8 bytes = modificadores, reservado, 6 teclas. Con más de 6
teclas a la vez, todas pasan a `0x01` (ErrorRollOver).

### JSON-RPC antiguo (sigue registrado)

| método | parámetros | notas |
|---|---|---|
| `keyboardReport` | `{"modifier", "keys": [≤6]}` | estado completo; no se suelta solo |
| `keypressReport` | `{"key", "press"}` | el aparato lleva el estado; una tecla que no es modificador **se suelta sola a los 100 ms** |
| `getKeyDownState` | — | su ausencia (-32601) es como su web detecta un firmware sin HID-RPC |
| `getKeyboardLedState` | — | `num_lock`, `caps_lock`… |

### HID-RPC binario (lo que usa su web, y el puente)

Byte 0 = tipo, el resto la carga. Enteros de varios bytes en **big-endian**.
Las longitudes están comprobadas en `internal/hidrpc/message.go` de 0.5.10.

| Tipo | Sentido | Forma | |
|---|---|---|---|
| ▸ 0x01 Saludo | los dos | `01 01` | |
| ▸ 0x02 KeyboardReport | C→A | `02 <mod> <k1..k6>` (carga: modificador y teclas) | el puente manda siempre las 6 |
| ▸ 0x03 PointerReport (absoluto) | C→A | `03 <x int32> <y int32> <botones u8>`: **carga de 9 bytes exactos** | |
| 0x04 WheelReport | — | **definido pero no atendido** (cae en `default`), también en 0.5.10 y 0.5.11 | |
| 0x05 KeypressReport | C→A | `05 <tecla> <1/0>` | |
| 0x06 MouseReport (relativo) | C→A | `06 <dx int8> <dy int8> <botones>` | |
| 0x07 KeyboardMacroReport | C→A | `07 <isPaste> <pasos u32>` y por paso `<mod> <k1..k6> <espera_ms u16>` (9 B/paso) | |
| 0x08 CancelKeyboardMacro | C→A | `08` | |
| 0x09 KeypressKeepAlive | C→A | `09` | |
| 0x32 KeyboardLedState | A→C | `32 <bits: num 0x01, caps 0x02, scroll 0x04…>` | |
| 0x33 KeysDownState | A→C | `33 <mod> <k1..k6>` | |
| 0x34 KeyboardMacroState | A→C | `34 <running> <isPaste>` | |

- ▸ **El saludo primero**: `01 01` por `hidrpc` y esperar `01 01` de vuelta. Su
  web reintenta cada segundo, hasta 10 veces. El puente hace lo mismo y, sin
  respuesta, dice que el firmware puede ser anterior a 0.4.7.
- Soltado automático: un 0x05 de una tecla que no es modificador se suelta a los
  100 ms salvo que llegue `09` cada 50 ms. ▸ **El 0x02 no se suelta solo**: la
  tecla sigue abajo hasta un informe vacío. El puente manda cada pulsación como
  informe completo y luego el vacío.
- Al cerrarse o perder la sesión, el aparato suelta todas las teclas.

### Pegar texto (su web)

El texto se traduce a teclas **en el navegador**, con la tabla de la
distribución elegida (`ui/src/keyboardLayouts/`); el aparato no traduce nada y
sólo guarda el código de la distribución. **La tabla tiene que casar con la
distribución del sistema del otro lado.** El puente lleva su propia tabla para
«U.S.» de macOS (`hid.py`); no usa la de su web.

La tabla `es_ES` de su web tiene errores leídos en el código (sin comprobar en
un aparato, **NO VERIFICADO**): la tilde va a `Key4`, que no es un nombre de
tecla; `¡` está marcado como tecla muerta; faltan `^`, `` ` `` y `~` sueltos.
Por eso el puente no soporta la española.

## e. Ratón

| Camino | Forma | Rango |
|---|---|---|
| ▸ Absoluto, HID-RPC | `struct.pack(">BiiB", 0x03, x, y, botones)` | x, y **0..32767** |
| Absoluto, JSON | `absMouseReport {"x","y","buttons"}` | igual |
| Relativo, HID-RPC | `struct.pack(">BbbB", 0x06, dx, dy, botones)` | int8 |
| ▸ Rueda | **sólo JSON**: `wheelReport {"wheelY", "wheelX"}` | **+wheelY sube**; ±127; su web manda ±1 por paso |

- Botones: 1 izquierdo, 2 derecho, 4 central, 8 atrás, 16 adelante.
- ▸ Su web manda por `hidrpc` (fiable) los informes en que **cambian** los
  botones, y por `hidrpc-unreliable-ordered` los que sólo mueven. Un clic:
  mover (botones=0), luego el mismo punto con 1, luego con 0.
- ▸ Píxel → HID: `x = round(px * 32767 / ancho_del_vídeo)`.
- ▸ La rueda llama a `AbsMouseWheelReport` si hay ratón absoluto y, si no, a la
  del relativo (`usb.go`).

## f. Vídeo

- ▸ Una pista H.264 (o H.265, ver §b), perfil **High**, VBR. El SDP no casa con
  el perfil que ofrece aiortc (42e01f), pero PyAV decodifica a partir del SPS.
  **NO VERIFICADO** con un aparato; contra el JetKVM falso de las pruebas, sí.
- Fotogramas clave: GOP = fps/2, un IDR cada ~0,5 s. El aparato **lee y tira el
  RTCP**, así que pedir un fotograma clave (PLI/FIR) no hace nada según el
  código. Un cliente de la comunidad dice que necesitó PLI: **NO VERIFICADO**.
  El puente espera hasta 5 s al primer fotograma decodificable.
- El vídeo sólo corre mientras hay al menos una sesión conectada.
- ▸ Resolución: `getVideoState` →
  `{"ready","streaming":0|1|2,"error":"no_signal|no_lock|out_of_range","width","height","fps"}`;
  el mismo objeto llega como evento `videoInputState`.
- **No hay ninguna URL de captura** en el aparato: capturar es decodificar la
  pista de vídeo.
- Calidad: `getStreamQualityFactor` / `setStreamQualityFactor {factor}`.

## g. Métodos JSON-RPC (`rpcHandlers` en `jsonrpc.go`)

- **Aparato**: `ping`, `reboot{force}`, `getDeviceID`, `getLocalVersion`,
  `factoryReset`, `get/setDevModeState`, `get/setSSHKeyState`, `get/setTLSState`,
  `get/setLocalLoopbackOnly`, `get/setDefaultLogLevel`, `get/setDisplayRotation`,
  `get/setBacklightSettings`, `getTimezones`; sólo 0.5.11: `getDeviceCapabilities`.
- **Nube / actualizaciones**: `deregisterDevice`, `getCloudState`, `setCloudUrl`,
  `getUpdateStatus`, `tryUpdate`, `get/setAutoUpdateState`, `get/setDevChannelState`…
- **Red**: `getNetworkState`, `get/setNetworkSettings`, `renewDHCPLease`,
  `getTailscaleStatus`, `get/setMqttSettings`…
- **Teclado y ratón**: `keyboardReport`, `keypressReport`, `absMouseReport`,
  `relMouseReport`, ▸ `wheelReport`, `getKeyboardLedState`, `getKeyDownState`,
  `wakeHost`, `get/setKeyboardLayout`, `get/setKeyboardMacros`, `setJigglerState`…
- **Vídeo / EDID**: ▸ `getVideoState`, `get/setStreamQualityFactor`,
  `get/setVideoCodecPreference`, `getEDID`, `setEDID`; sólo 0.5.11:
  `setVideoStreamPaused`.
- **USB / medio virtual**: `getUSBState`, `get/setUsbEmulationState`,
  `setUsbDeviceState`, `mountWithHTTP`, `unmountImage`…
- **Alimentación, serie, Wake-on-LAN, audio**: `setATXPowerAction`,
  `get/setSerialSettings`, `sendWOLMagicPacket`, `get/setAudioConfig`…

El puente sólo usa los marcados ▸. Nunca toca alimentación, red, actualizaciones
ni medio virtual.

## h. Otros clientes

No hay API oficial: el protocolo de arriba es la API. Clientes de la comunidad
consultados al escribir el cliente (repositorios públicos):
`jenrzzz/kvm-bridge` (Python, aiortc, HTTP con capturas en PNG),
`shvartzj1/jetkvm-mcp` (Python, aiortc + PyAV, servidor MCP; su manejo de
candidatos casa con el código), `tfyl/jkvm` (Go/pion, «requiere 0.5.9+»),
`LeeroyDing/jetkvm-mcp` (Go/pion; confirma la rueda por JSON-RPC y los IDR cada
~0,5 s), `YokihitoOkiBiz/jetkvm-mcp` (Playwright sobre su web, usando
`window.__kvmTestHooks`), `agners/pyjetkvm-client`.

## i. Historia del protocolo

| Cambio | Desde | Cómo se sabe |
|---|---|---|
| HID-RPC binario, canales `hidrpc*`, `09` | **0.4.7** | `internal/hidrpc` está en 0.4.7 y no en 0.4.6 |
| Negociación H.265 | 0.5.5 o 0.5.6 | `webrtc.go` |
| `POST /webrtc/session` **quitado** | **0.5.9** | rutas de `web.go` (está en 0.5.8) |
| GOP 60 → 30 → fps/2 | 0.5.4 → 0.5.8 → 0.5.11 | `video.c` |
| Métodos de entrada JSON-RPC | sin cambios desde 0.4.8 | `rpcHandlers` |
| Sin cambios en lo que usa el cliente | 0.5.9 → 0.5.10 → 0.5.11 | diff de los archivos de arriba (13-nov) |

---

## Lo que no se ha visto con un aparato (NO VERIFICADO)

Esto sólo se sabe con el JetKVM delante (ver `docs/pruebas-con-el-aparato.md`):

1. Que aiortc completa ICE con los candidatos que llegan por goteo (los clientes
   de la comunidad dicen que sí), y el valor exacto de `sdpMid` que manda pion.
2. Que PyAV decodifica el H.264 *High* del aparato aunque el SDP diga 42e01f.
3. Cada cuánto llegan fotogramas con la pantalla quieta, y el ruido del vídeo
   real: el umbral de «la pantalla no cambió» (`motor.UMBRAL_PIXEL`, cuadros de
   64×32) está calibrado con H.264 local.
4. Que el saludo HID (`01 01`) se contesta en el primer segundo.
5. Que `otherSessionConnected` llega antes de que se cierre la conexión.
6. La resolución que entrega con el Mac real (y si el Mac la cambia al ver un
   monitor nuevo).
7. Cómo reacciona macOS al teclado USB nuevo (el asistente de teclado; ANSI/ISO).

## Si el cliente no conecta o se comporta distinto

1. La bitácora del panel y
   `uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm comprobar`,
   que dice si el aparato responde, si la contraseña entra y qué firmware tiene.
   Sin `--sin-entrar` y con el puente parado, **entra en el JetKVM y le cierra
   su web** a quien la tenga abierta en un navegador: ciérrala antes.
2. Busca el paso que falla en `jetkvm.JetKVM.conectar`: cada uno levanta
   `AparatoNoDisponible` con un mensaje distinto (contraseña, canales que no se
   abren, saludo HID, vídeo que no llega).
3. Compara con la sección de arriba y con el código de **su** versión: clona el
   repositorio en una carpeta aparte y mira la etiqueta `release/<versión>`
   (`git diff release/0.5.10 release/<la suya> -- web.go webrtc.go cloud.go
   jsonrpc.go hidrpc.go internal/hidrpc`).
4. Un arreglo se prueba primero contra `tests/jetkvm_falso.py` (ajusta el falso
   a lo que hace el aparato, con una prueba que falle) y después contra el
   aparato: conecta, mira la pantalla (`ver_pantalla`) y teclea sólo en una
   pestaña de script nueva y vacía, nunca en un documento real.
