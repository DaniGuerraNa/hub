---
name: instalar-hub
description: Instala el hub en esta máquina. Úsala cuando pidan «instala este repo», «instala el hub», «ponlo a funcionar» o «set this up» dentro del repositorio del hub.
---

# Instalar el hub

Este repositorio trae su instalador. Tu trabajo no es improvisar los pasos: es
**correr el diagnóstico, enseñarlo, pedir permiso para lo que falte, instalar y
verificar que responde**.

## 🔴 La regla que no se salta

**No instales nada del sistema sin permiso explícito, una cosa cada vez.**

Estás en la máquina de alguien. Un instalador que resuelve dependencias solo es
la misma clase de acción consecuente que parar un contenedor ajeno: puede que
esa persona quiera `tmux` de otra versión, o que ese `apt install` arrastre algo
que no espera. Enseña qué falta, di el comando exacto, y **espera**.

## Pasos

### 1. Diagnostica

```bash
bash scripts/doctor.sh
```

Enseña su salida **tal cual**, sin resumirla. Cada línea trae la consecuencia de
lo que falta, y esa consecuencia es lo que le permite decidir.

- Sale **0**: todo lo imprescindible está. Sigue al paso 3.
- Sale **1**: falta algo. Ve al paso 2.

### 2. Si falta algo imprescindible

Para cada ausencia, di el comando que la resuelve —el doctor ya lo imprime— y
pide confirmación. Cuando confirme, ejecútalo y **vuelve a correr el doctor**:
instalar no es haber instalado hasta que la comprobación lo dice.

Casos que vas a ver:

| Falta | Qué pasa |
|---|---|
| `claude` | Sin Claude Code no hay asistente ni medición de uso. Hay que instalarlo desde <https://claude.com/claude-code>; no es un paquete de `apt`. |
| `systemd --user` | En WSL suele estar desactivado. Requiere editar `/etc/wsl.conf` y **`wsl --shutdown` desde Windows**: avísale de que se cierra la sesión de WSL. |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, y después abrir una shell nueva o exportar el PATH. |

Los **opcionales** (`docker`, `rg`) no bloquean. Menciónalos con su consecuencia
y sigue; instalarlos es decisión suya, no tuya.

### 3. Instala

```bash
bash scripts/instalar.sh
```

Es idempotente y no pisa nada: si ya hay un `projects.yml` en `HUB_HOME`, lo
respeta. Genera los servicios de systemd con las rutas reales de **este** clon,
los arranca y comprueba las siete pantallas.

Si el script falla en el último paso, no lo des por bueno: enseña
`journalctl --user -u hub-web -n 40 --no-pager`.

### 4. Ofrece el asistente

El asistente es un chat que sigue al usuario por todas las pantallas: por debajo
es `claude` en una ventana de tmux, y el hub pinta su transcript.

Pregunta si lo quiere. Si dice que sí:

```bash
bash scripts/sembrar-asistente.sh
```

y **añade al registro** el bloque `tipo: asistente` que el script imprime. Si
dice que no, no hagas nada: sin un proyecto de ese tipo la pestaña ni se pinta.

### 5. Verifica y cuenta

```bash
systemctl --user status hub-web hub-snapshotter --no-pager | head -20
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/
```

Dile:

- La URL: <http://127.0.0.1:8787>
- Dónde están sus datos: `~/.local/share/hub/` — y que `projects.yml` es el
  registro que va a editar.
- Que la portada trae una guía de primer arranque mientras no tenga proyectos.
- Lo siguiente: **usa la skill `anexar-proyecto`** para registrar el primero.

## Qué NO hacer

- **No edites `projects.yml` por tu cuenta** durante la instalación. Declarar un
  proyecto es la skill `anexar-proyecto`, que antes mira qué hay dentro.
- **No abras el puerto a la red.** El hub sirve una terminal con acceso de shell
  y hoy sólo lo protege el bind a `127.0.0.1`. Si te piden exponerlo, di que
  antes hace falta autenticación.
- **No des por bueno un `systemctl start` que devuelve 0.** Arrancar no es
  funcionar: lo que cuenta es el 200 de las pantallas.
