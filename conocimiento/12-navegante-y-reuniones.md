# Navegante y Reuniones

Dos pantallas que hacen algo fuera del hub: **Navegante** maneja un navegador
de verdad, y **Reuniones** graba una reunión de otro monitor y la procesa. Lo
que hace el trabajo viene con el hub, en la carpeta `componentes/` del clon,
pero hay que prepararlo una vez.

Mientras no está preparado, cada pantalla enseña sus pasos: qué falta, por qué
y cómo se consigue, medido en tu máquina. Lo mismo, desde el asistente:

```bash
hub componentes                 # qué falta en cada uno
hub preparar navegante          # o reuniones
```

## «Preparar con Claude»

El botón (y `hub preparar`) abre en `/trabajo` una ventana en la carpeta del
componente con `claude` y el encargo de prepararlo **escrito y sin lanzar**.
Pulsa Enter ahí. Esa sesión pide permiso antes de cada orden, y lo que necesite
`sudo` (Node, ffmpeg, Xvfb) te lo dice para que lo instales tú.

Se prepara con `uv sync --frozen` y `npm ci`, que no reescriben los archivos de
bloqueo. Importa: `componentes/` está dentro del clon, y un archivo cambiado ahí
haría que `actualizar.sh` se parase la próxima vez.

**«Guíame»** abre el chat del asistente con la pregunta hecha, si lo que quieres
es que te lo explique.

## Navegante

Un Chrome con perfil propio que maneja Claude, y un **guardián** que pausa cada
petición que modifica algo hasta que tú la permites en la pantalla. Se le enseña
un flujo haciéndolo una vez, y lo repite.

Lo que necesita, en `componentes/navegador-lab`:

| Paso | A mano |
|---|---|
| Su entorno | `uv sync --frozen && npm ci` |
| Un Chrome o Chromium | Si no tienes uno en el PATH: `npx playwright install chromium` |
| Xvfb *(opcional)* | `sudo apt install xvfb`. Sin él el navegador va sin ventana, y algunos sitios lo bloquean |

Preparado, la pantalla enseña los mandos: encender, vigilar con una política,
la vista en vivo, grabar y correr flujos. Cómo se usa paso a paso está en
`componentes/navegador-lab/README.md`, y Claude lo sabe por su skill
`navegador` si abres `claude` en esa carpeta.

Sus datos —el perfil de Chrome con tus cookies, las preguntas del guardián, las
corridas— viven en `~/.local/share/navegador-lab/`, fuera del clon. **No se
respaldan.**

## Reuniones

Graba la pantalla, el audio **sólo de la aplicación** de la reunión y tu micro
aparte. Luego lo procesa en esta máquina: transcripción con Whisper, y un
resumen con tareas y decisiones. Al resumen sólo va el texto de la
transcripción, nunca el audio.

Son dos piezas:

1. **El procesado, en WSL** (`componentes/reuniones`): `uv sync --frozen`. Con
   una GPU NVIDIA transcribe mucho más rápido; sin ella va en la CPU. `ffmpeg`
   hace falta para comprimir las grabaciones (`sudo apt install ffmpeg`).
2. **El agente, en Windows.** Es el único que ve tu escritorio y el audio de las
   aplicaciones. No abre ningún puerto: llama al hub cada segundo.

Para el agente, la pantalla va en orden:

1. **Dónde va en Windows.** Una carpeta, por ejemplo `C:\reuniones\agente`.
   Las grabaciones irán a la de al lado (`C:\reuniones\grabaciones`), y el hub
   las lee desde WSL (`/mnt/c/reuniones/grabaciones`).
2. **Copiar el agente.** El hub deja ahí sus archivos, con el puerto de tu hub
   ya puesto.
3. **Instalarlo.** Hace falta [uv para Windows](https://docs.astral.sh/uv/)
   (en PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`).
   Después, doble clic en `instalar.cmd` dentro de esa carpeta: prepara su
   entorno, lo deja arrancando al iniciar sesión y lo lanza.
4. **La llave.** «Generar la llave»: el agente demuestra con ella que es él.
   El hub la escribe en la carpeta del agente y guarda sólo su huella.

En unos segundos la pantalla dice «agente conectado» y ya puedes grabar.

**Separar las voces** de los demás (Persona 1, Persona 2…) es opcional y pide
un token de Hugging Face una vez: los pasos están en
`componentes/reuniones/README.md`, «Separar las voces».

🔴 Lo grabado es contenido de tu trabajo y de otras personas. Se queda en tu
máquina; lo único que sale es el texto de la transcripción, para el resumen.

## Si algo no va

- **Navegante dice que falta el entorno después de prepararlo:** mira la
  ventana de `/trabajo` donde corrió; si `npm ci` falló, suele ser que no hay
  Node (`node --version`).
- **Reuniones: «no se ve … desde aquí»** al copiar el agente: esa unidad de
  Windows no está montada en WSL. Usa una que sí (`ls /mnt`).
- **El agente no conecta:** su log está junto a su carpeta (`C:\reuniones\agente.log`).
  Si dice 401, falta la llave o es una vieja: sácala otra vez.
- **Actualizar el agente** tras una versión nueva del hub: «Copiar el agente»
  otra vez (no toca la llave), cierra `pythonw.exe` en el Administrador de
  tareas y abre `instalar.cmd`.

## Variables

Ninguna hace falta. Sirven si ya tenías los componentes en otro sitio.

| Variable | Por omisión | Para qué |
|---|---|---|
| `NAV_LAB` | `componentes/navegador-lab` del clon | Dónde está el laboratorio |
| `NAV_DATOS` | `~/.local/share/navegador-lab` | Sus datos: perfil, preguntas, corridas |
| `REUNIONES_PROYECTO` | `componentes/reuniones` del clon | Dónde está el procesado |
| `REUNIONES_AGENTE` | la carpeta que elegiste, vista desde WSL | Dónde está el agente |
| `REUNIONES_RAIZ` | junto al agente (`…/grabaciones`) | Dónde están las grabaciones |
