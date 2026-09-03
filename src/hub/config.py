"""Rutas y ajustes. Todo derivado de una sola raíz para que los tests la puedan mover."""

from __future__ import annotations

import os
from pathlib import Path

# Raíz de datos del hub. Sobreescribible con HUB_HOME (los tests lo usan).
HUB_HOME = Path(os.environ.get("HUB_HOME", Path.home() / ".local/share/hub"))

DB_PATH = HUB_HOME / "hub.db"

# El repo, para la semilla del registro y para resolver rutas del propio hub.
RAIZ_REPO = Path(__file__).resolve().parents[2]

# Dónde se instalan los kits: un repositorio local por `id` y versión, al estilo
# de `~/.m2/repository`. Todas las versiones coexisten, así que dos proyectos
# pueden usar versiones distintas del mismo kit sin migrar a la vez.
HUB_KITS = Path(os.environ.get("HUB_KITS", HUB_HOME / "kits"))


def projects_yml() -> Path:
    """El registro central: fuente de verdad de qué proyectos existen (decisión 7).

    Se resuelve en tres pasos, y el tercero es compatibilidad deliberada:

    1. `HUB_PROJECTS_YML`, para los tests y para instalaciones a medida.
    2. `HUB_HOME/projects.yml` — su sitio. **Los datos del usuario no viven en el
       árbol del código**: el repo se comparte y el registro lleva sus rutas
       reales, así que dentro del repo cada `pull` chocaría contra sus ediciones.
    3. El `projects.yml` del repo, si todavía existe. Sin este paso, el instante
       entre cambiar esto y mover el archivo deja al hub sin registro — y el hub
       es lo que se usa todos los días.

    Es una función y no una constante porque el instalador crea el archivo
    *después* de que el proceso arranque: una constante evaluada al importar se
    quedaría con la respuesta vieja.
    """
    declarado = os.environ.get("HUB_PROJECTS_YML")
    if declarado:
        return Path(declarado)
    en_home = HUB_HOME / "projects.yml"
    if en_home.is_file():
        return en_home
    en_repo = RAIZ_REPO / "projects.yml"
    return en_repo if en_repo.is_file() else en_home


# Semilla del registro: lo que el instalador copia la primera vez. Nunca pisa un
# `projects.yml` que ya exista.
PROJECTS_EJEMPLO = RAIZ_REPO / "projects.ejemplo.yml"

# Cada cuánto muestrea el snapshotter. Un cierre abrupto no dispara hooks,
# así que la captura es continua y no "al cerrar" (decisión 18).
INTERVALO_SEGUNDOS = int(os.environ.get("HUB_INTERVALO", "20"))

# Ventana rodante de snapshots normales. Los preservados (último antes de una
# muerte detectada) nunca se podan.
RETENCION_SNAPSHOTS = int(os.environ.get("HUB_RETENCION", "50"))

def canal_yml() -> Path:
    """Los ajustes del canal de consulta: hoy, el puntero al token del bot.

    Archivo aparte y no una sección de `projects.yml` por dos motivos. El primero
    es que `conexiones.revisar_secretos()` vigila ese archivo contra campos que
    huelan a credencial, y meter ahí algo llamado `token_ref` invita a que el
    siguiente pegue el valor. El segundo es que este archivo lo lee el relé, que
    es un proceso distinto de `hub-web`: cuanto menos comparta con él, menos
    superficie.

    🔴 Aquí va el PUNTERO, nunca el token (regla dura 5).
    """
    declarado = os.environ.get("HUB_CANAL_YML")
    return Path(declarado) if declarado else HUB_HOME / "canal.yml"


WEB_HOST = os.environ.get("HUB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("HUB_PORT", "8787"))


def asegurar_home() -> Path:
    HUB_HOME.mkdir(parents=True, exist_ok=True)
    return HUB_HOME
