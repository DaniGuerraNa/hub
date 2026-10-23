# reuniones

Grabar la reunión que tienes en otro monitor mientras trabajas, y leerla
después procesada: resumen, lo que te toca, tareas, decisiones, y la
transcripción con las capturas de pantalla intercaladas.

Se maneja desde la pantalla **Reuniones** del hub.

## Cómo funciona

```
 Windows (tu sesión)                         WSL
 ┌──────────────────────┐   latido 1/s   ┌──────────────────────────┐
 │ agente (pythonw)     │ ─────────────► │ hub /api/reuniones/latido│
 │  · monitor a 1 fps   │ ◄───────────── │  devuelve la orden       │
 │  · audio SÓLO de app │     orden      └────────────┬─────────────┘
 │  · tu micro aparte   │                             │ al terminar
 └─────────┬────────────┘                             ▼
           │ escribe                      reuniones procesar <id>
           ▼                              · faster-whisper en la GPU (local)
  <base>\grabaciones\<id>\   ◄────  · une pistas: «Tú» / «Reunión»
                                          · resumen con claude -p (sólo el texto)
```

- **El agente no escucha puertos**: pregunta al hub. Desde Windows se llega a
  WSL; al revés (red NAT), no. Y no depende de que WSL pueda lanzar `.exe`.
- **Audio de la aplicación, no del sistema**: WASAPI process loopback
  ([proctap](https://github.com/m96-chan/ProcTap)). Si suena Spotify a la vez,
  no entra.
- **Las pistas cuadran con el reloj**: Windows sólo entrega audio mientras la
  aplicación suena; el agente rellena los silencios para que la muestra N sea
  siempre el instante inicio + N/48000.
- **Capturas**: 1 por segundo, pero sólo se guarda la que difiere de la última
  guardada (umbral `REUNIONES_UMBRAL`, 4 sobre 255 de diferencia media).

## Espacio

Grabando: ~1 GB por hora (WAV de la aplicación 690 MB/h + micro 345 MB/h) más
las capturas (~100 KB cada una; cuántas, según lo que se mueva la pantalla).
**Comprimir** (botón en el hub, a demanda) pasa las pistas a Opus 24 kbps mono:
3 h quedan en ~65 MB de audio. Comprueba la duración antes de borrar el WAV y
no se hace mientras la reunión se procesa (medido: borraba lo que Whisper leía).

## Instalar el agente en Windows

Lo normal es hacerlo desde la pantalla **Reuniones** del hub, que va paso a
paso. A mano:

1. Instala [uv](https://docs.astral.sh/uv/) para Windows, en PowerShell:
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. Copia la carpeta `agente/` a Windows, por ejemplo a `C:\reuniones\agente\`.
   Las grabaciones irán a la carpeta de al lado (`C:\reuniones\grabaciones\`)
   y el log a `C:\reuniones\agente.log`. El hub las encuentra sabiendo sólo
   dónde está el agente.
3. Si tu hub no escucha en `8787`, cambia `REUNIONES_HUB` en `iniciar.cmd`.
4. Doble clic en `instalar.cmd`: prepara el entorno (`uv sync`), lo deja
   arrancando al iniciar sesión (un `.vbs` en la carpeta de Inicio) y lo lanza.
5. **La llave** (decisión 280 del hub): en la pantalla Reuniones, «Generar la
   llave». El hub la escribe en `token`, junto a `agente.py`, y el agente la
   lee en cada latido, sin reiniciarlo. Si el hub no ve esa carpeta, te la
   enseña una vez para que crees el archivo `token` a mano. Sin llave, el hub
   contesta 401 y el log lo dice una vez por minuto.

**Actualizarlo o reiniciarlo:** copia el `agente.py` nuevo, cierra el
`pythonw.exe` del agente (Administrador de tareas) y vuelve a abrir
`instalar.cmd`. Ojo: `iniciar.cmd` intenta no lanzar dos agentes, pero lo
comprueba por el título de ventana, que `pythonw` no tiene. Ciérralo antes de
relanzar.

## Requisitos del lado WSL

- `ffmpeg`: para comprimir (Whisper lee `.opus` con su propio PyAV).
- GPU NVIDIA con CUDA (opcional). Sin ella, Whisper va en CPU, mucho más lento.
- `claude` en el PATH, para el resumen. Sin él, usa `--sin-resumen`.

## Separar las voces (una vez)

Tu voz se reconoce siempre, porque tu micro se graba aparte. Para separar a
**los demás** en Persona 1, Persona 2… se usa
[pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1),
que corre en tu GPU. El modelo está en Hugging Face con acceso restringido, así
que la primera vez hay que autorizar su descarga. Son unos cinco minutos:

1. **Crea una cuenta** gratuita en <https://huggingface.co/join>.
2. **Acepta las condiciones del modelo:** entra en
   <https://huggingface.co/pyannote/speaker-diarization-community-1>, rellena el
   formulario (empresa y uso, puede ser «personal») y pulsa *Agree and access
   repository*.
3. **Crea un token de lectura:** <https://huggingface.co/settings/tokens> →
   *Create new token* → tipo **Read** → ponle un nombre (`reuniones`) → copia
   el valor (`hf_…`). Solo se enseña una vez.
4. **Guárdalo en tu máquina**, en una terminal de WSL:
   ```bash
   uv run --project <carpeta-de-reuniones> hf auth login
   ```
   Pega el token cuando lo pida. Si pregunta *Add token as git credential?*,
   contesta **n**. Queda en `~/.cache/huggingface/token`, fuera de este
   repositorio y fuera del hub.
5. **Prueba:** en `/reuniones`, abre una reunión ya procesada y pulsa
   **«Separar las voces»**. La primera vez descarga el modelo (unos cientos de
   MB) y tarda un poco más. Al terminar aparece la tarjeta **«Quién habla»**,
   donde pones los nombres.
6. *(Opcional)* Con el modelo ya descargado, el token no se vuelve a usar,
   porque se trabaja sin conexión. Si no quieres dejarlo guardado:
   `uv run --project <carpeta-de-reuniones> hf auth logout`.

Si algo falla, la reunión se procesa igual, con todos los demás como
«Reunión», y la página dice por qué. Lo habitual es «no se pudo descargar…»:
falta el paso 2 o el 4.

La telemetría de pyannote, que manda métricas de uso a `otel.pyannote.ai`, va
**apagada** (`voces.py`). El audio no sale de la máquina en ningún caso.

Desde la línea de comandos:

```bash
uv run reuniones voces 20261021-192505 --resumen               # separar y rehacer el resumen
uv run reuniones nombres 20261021-192505 "Persona 1=Ana" --resumen
```

## Variables

| Variable | Dónde | Por omisión | Para qué |
|---|---|---|---|
| `REUNIONES_HUB` | agente | `http://127.0.0.1:8787` | A qué hub llama el latido |
| `REUNIONES_RAIZ` | agente / WSL | junto al agente (`<base>\grabaciones`) / la que diga la pantalla Reuniones | Dónde están las reuniones: la misma carpeta, vista desde cada lado |
| `REUNIONES_TOKEN` | agente | — | La llave en claro; si no está, se lee el archivo |
| `REUNIONES_TOKEN_ARCHIVO` | agente | `token` junto a `agente.py` | Dónde está la llave |
| `REUNIONES_LOG` | agente | `<base>\agente.log` | Log del agente |
| `REUNIONES_UMBRAL` | agente | `4.0` | Diferencia media (0-255) para guardar una captura |
| `REUNIONES_WHISPER` | WSL | `large-v3` | Modelo de faster-whisper |
| `REUNIONES_MODELO` | WSL | `sonnet` | Modelo de `claude -p` para el resumen |
| `REUNIONES_DIARIZADOR` | WSL | `pyannote/speaker-diarization-community-1` | Modelo para separar las voces |

## La carpeta de una reunión

El contrato completo está en `src/reuniones/carpeta.py`. Esto es lo que contiene:

- `meta.json`: lo escribe el agente.
- `reunion.wav` y `micro.wav`, que pasan a `.opus` si se comprimen.
- `fotos/<s>.jpg`.
- Lo que deja el procesado: `transcripcion.*`, `resumen.*` y `procesado.json`.
- `nombres.json`: el nombre de cada voz (`{"Persona 1": "Ana"}`), si se pusieron.
- Lo que deja la compresión: `comprimido.json` y la marca `comprimiendo` mientras dura.

## A mano

```bash
uv run reuniones listar
uv run reuniones procesar 20261020-121303            # --sin-resumen, --rehacer
uv run reuniones comprimir 20261020-121303 [otra…]   # nunca mientras graba o procesa
```
En Windows: `.venv\Scripts\python.exe agente.py inventario` (qué ve) o
`agente.py prueba --segundos 10 --app ms-teams.exe --monitor 3 --micro 49`.
El arnés con el que se midió está en `agente/pruebas/`.

## Tests

```bash
uv run pytest -q     # incluye una transcripción real de dos pistas
```
