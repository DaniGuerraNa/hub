# Instalar el puente

Escrito para que lo siga Claude Code con la persona delante. **Pide permiso
antes de cada paso marcado 🔐**, y no hagas los que dicen «lo hace la persona».

## 1. Lo que hace falta

- Linux o WSL2 (Ubuntu probado: 24.04 en WSL2). macOS: **sin probar**.
- `git`, `curl`, `tmux`, [`uv`](https://docs.astral.sh/uv/) y Claude Code con
  la cuenta de la persona ya iniciada (`claude --version` responde).
- Las fuentes del Mac simulado: en Ubuntu, `sudo apt install fonts-dejavu`
  (el metapaquete; `fonts-dejavu-mono` no existe en 22.04, y si apt no
  encuentra un nombre no instala ninguno).
- El equipo y el JetKVM en la misma red.

🔐 Instalar lo que falte con `sudo apt install …` es tocar el sistema: pregunta.

## 2. El código

Puede llegar de dos formas:

- **Clon propio** del puente: `git clone <dirección del repositorio> puente-kvm`
  (o donde lo deje la persona).
- **Dentro de otro repositorio** (p. ej. en `componentes/puente-kvm`): ya está
  ahí, no se clona aparte. En este caso, el espacio de trabajo va fuera (ver
  `PUENTE_TRABAJO` más abajo).

En la carpeta del código:

```bash
uv sync --frozen
uv run --frozen puente-kvm comprobar --sin-entrar
```

**Siempre `--frozen`** con `uv sync` y `uv run`: sin él, uv puede reescribir
`uv.lock`, que es un archivo versionado, y dentro de otro repositorio un
archivo versionado modificado para la actualización de ese repositorio.
Ningún archivo del repositorio se modifica al instalar: si `git status` sale
con cambios, algo no va bien.

`comprobar --sin-entrar` dice qué falta y cómo arreglarlo **sin entrar en el
JetKVM**, y basta para saber si el puente está bien instalado. Sin
`--sin-entrar`, si el puente no está en marcha, entra en el aparato con la
contraseña para leer su firmware, y eso **cierra la web del JetKVM** si la
persona la tiene abierta en un navegador (el aparato guarda una sola sesión).

## 3. La contraseña del JetKVM (lo hace la persona)

La contraseña no va en ningún archivo del repositorio, ni en los ajustes, y
**Claude no la lee ni la escribe** (sus permisos lo prohíben). La persona:

```bash
install -D -m 600 /dev/null ~/.config/puente-kvm/entorno
nano ~/.config/puente-kvm/entorno       # una línea: JETKVM_CLAVE=la-contraseña
```

Si lleva espacios o comillas, entre comillas dobles. Si el JetKVM no tiene
contraseña, el archivo puede quedar vacío. `comprobar` dice si los permisos
son 600 y si la variable tiene valor, nunca el valor.

## 4. Arrancar el servicio

**Con systemd** (en WSL hace falta `systemd=true` en `/etc/wsl.conf`;
`comprobar` dice si está):

🔐 Esto crea un servicio de usuario que arranca solo al entrar en la sesión:

```bash
bash scripts/servicio.sh unidad      # enseña la unidad, sin tocar nada: revísala con la persona
bash scripts/servicio.sh instalar    # la escribe en ~/.config/systemd/user y arranca
```

La unidad lleva la carpeta real de este clon y el `uv` que encuentre, y se
genera fuera del repositorio. Si el código se mueve, se vuelve a instalar.

**Sin systemd** (WSL sin systemd, macOS): en su propia terminal o en una
ventana de tmux,

```bash
bash scripts/arrancar.sh             # Ctrl+C lo para
```

🔴 **La web del puente no se publica ni se reenvía.** Escucha sólo en
`127.0.0.1` y así se queda: ni `0.0.0.0`, ni reenviar el puerto (router,
`ssh -R`, proxies, túneles, servicios para publicar en una red privada), ni
siquiera «un momento». Dentro hay una terminal con Claude Code: quien llegue a
esa web tiene una shell en este equipo y el teclado del Mac.

## 5. Comprobar que quedó funcionando

1. `uv run --frozen puente-kvm comprobar --sin-entrar` (desde la carpeta del
   código): «el puente: en marcha» y nada imprescindible falta.
2. Abre **http://127.0.0.1:8794**. Arriba: «Simulador · 1920×1080» y «Tú tienes
   el Mac». A la izquierda, el Mac simulado en directo.
3. A la derecha se abre Claude Code. La primera vez pregunta si confías en la
   carpeta: contesta la persona. Si pregunta por el servidor MCP `puente-kvm`,
   apruébalo.
4. Pídele en esa terminal «¿cómo está el puente?»: tiene que usar la
   herramienta `estado` y contestar quién tiene el control.
5. La barra de la terminal dice el modelo y la versión de Claude Code con que
   corre: por omisión **Fable 5.2**, que pide Claude Code **2.1.322** o
   posterior. `comprobar` dice qué `claude` abre el puente (con su PATH, no el
   de tu shell) y avisa si en el equipo hay varios de versiones distintas. Si
   el que abre es más viejo, el puente no lo arranca con Fable a ciegas: lo
   dice y propone actualizar Claude Code o elegir otro modelo en
   **Ajustes → Modelo de Claude**.

## El modelo y las conversaciones

- **Modelo:** Ajustes → Modelo de Claude. Lista cerrada, por el nombre exacto
  del modelo (nunca por un alias): Fable 5.2 (por omisión), Opus 5.5, Sonnet 5,
  o «el de mi Claude Code» (no le pasa ninguno). Vale para la siguiente
  conversación que se abra o se retome.
- **Conversaciones:** el nombre de la abierta, en la barra de la terminal, abre
  la lista: nueva, cambiar, reabrir, renombrar, quitar. Una sola abierta a la
  vez; cambiar cierra la abierta (Claude Code la guarda) y devuelve el control
  del Mac a la persona. La lista vive en `PUENTE_HOME/conversaciones.json`;
  quitar una de la lista no borra nada de Claude Code. Claude Code guarda las
  conversaciones según la carpeta: si se cambia `PUENTE_TRABAJO`, las de antes
  salen marcadas «otra carpeta» (se retoman, pero trabajan en la nueva).

## Opcional

| Variable | Para qué | Por omisión |
|---|---|---|
| `PUENTE_PUERTO` | otro puerto | 8794 |
| `PUENTE_HOME` | dónde guarda lecturas, cambios y bitácora | `~/.local/share/puente-kvm` |
| `PUENTE_TRABAJO` | dónde trabaja Claude (y `trabajo/`), fuera del código | la carpeta del código |
| `PUENTE_ENTORNO` | el archivo de la contraseña | `~/.config/puente-kvm/entorno` |

Con systemd, ponlas al instalar (`PUENTE_PUERTO=8800 bash scripts/servicio.sh
instalar`): quedan en la unidad.

**Si el código vive dentro de otro repositorio, `PUENTE_TRABAJO` va siempre
fuera de él** (p. ej. `~/puente-trabajo`): así lo traído del Mac no queda dentro
de un clon, y Claude no carga el `CLAUDE.md` del repositorio que lo contiene. El
puente prepara esa carpeta solo (enlaces a las reglas, skills y permisos, su
`.mcp.json` y un repositorio git que no guarda nada). Desde esa carpeta,
`uv run puente-kvm …` a secas falla (no es la del código): las órdenes del
puente se lanzan contra la carpeta del código, que la sesión de Claude tiene en
`PUENTE_CODIGO`:

```bash
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm comprobar --sin-entrar
```

Si `PUENTE_HOME` no es el de por omisión, Claude preguntará antes de leer las
lecturas: sus permisos sólo dejan leer sin preguntar `~/.local/share/puente-kvm`.

## Actualizar

- **Clon propio:** en la carpeta del código,
  `git pull && uv sync --frozen && bash scripts/servicio.sh reiniciar`.
- **Dentro de otro repositorio:** el puente se actualiza con ese repositorio y
  su propio actualizador. **Aquí no se hace `git pull`**: actualizaría el
  repositorio de fuera saltándose su actualizador. Cuando ya esté actualizado,
  sólo se reinicia el puente: `bash scripts/servicio.sh reiniciar` (sin
  systemd, parar y volver a lanzar `bash scripts/arrancar.sh`).

`/api/estado` dice la versión que corre: si no cambia tras actualizar, falta
reiniciar.

**La conversación de Claude sobrevive al reinicio** (vive en tmux, fuera del
servicio, a propósito), y con ella su servidor MCP con el código de antes. Tras
actualizar, en la terminal del puente: el nombre de la conversación →
**Reabrir**. Así Claude Code vuelve a arrancar, con el código y el modelo de
ahora, y retoma la conversación.

## Quitar

1. Quitar su servicio: `bash scripts/servicio.sh quitar`. Cierra también la
   conversación de Claude abierta (la sesión de tmux `puente-claude`, que si no
   sobreviviría); Claude Code la tiene guardada. Sin systemd: parar
   `arrancar.sh` y cerrar esa sesión (`tmux kill-session -t =puente-claude`).
2. Se queda, a propósito, hasta que la persona lo borre a mano:
   - **la carpeta de trabajo** (`PUENTE_TRABAJO`, o `trabajo/` dentro del
     código si no se cambió), **con lo leído del Mac**;
   - los datos del puente (`PUENTE_HOME`: lecturas, cambios, capturas y
     bitácora, que también llevan contenido del trabajo);
   - el archivo de la contraseña (`~/.config/puente-kvm/entorno`).

## Después

Con el puente funcionando, el aparato: `docs/pruebas-con-el-aparato.md`.
