"""El contrato del tercer agente: convierte la maqueta en el sistema de verdad.

🔴 **Decisión 244.** Los dos primeros agentes producen una maqueta estática
para que la persona pasee por su sistema y lo corrija mientras cambiar es
barato. Cuando dice «así», y quien aprueba pulsa «Implementar», entra éste:
toma la maqueta como especificación —**lo que se ve es lo que hay que hacer**—
y la vuelve un sistema con base de datos, que corre en un contenedor propio en
el servidor detrás de Caddy, con usuario y contraseña.

Lo que NO hace, a propósito, y por qué:

- **No escribe el acceso.** La contraseña la pone Caddy delante (`basic_auth`)
  con un hash que genera el hub; el agente no ve la contraseña ni escribe
  código de login. Menos código escrito a partir de texto ajeno donde más
  duele equivocarse.
- **No guarda secretos** (regla dura 5). La contraseña se manda una vez por
  el canal y no se apunta; lo que viaja al servidor es el hash.
- **No sale de `app/`** ni instala nada: FastAPI, uvicorn y la librería
  estándar, que es lo que la imagen trae. Lo que falte, no existe.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
from pathlib import Path

from . import constructor, encargos, entrevistador

MODO = entrevistador.MODO
CARPETA_APP = "app"
ACCESO = "acceso.bcrypt"

INSTRUCCIONES = """\
# Implementa el encargo «{encargo}»

La maqueta ya está aprobada y usada: **es la especificación**. Tu trabajo es
convertirla en el sistema de verdad, con base de datos, sin cambiar lo que se
ve ni lo que hace.

## Lo que hay aquí

    sitio/         la maqueta publicada: lo que ella vio, usó y aprobó
    {app}/          donde construyes. Ya trae:
      main.py      el arranque: FastAPI, la base SQLite y las páginas servidas
      static/      copia de la maqueta, para que la adaptes
    informe.md     el plan de la última ronda
    ficha.json     lo que contó, con sus palabras

Léelos en ese orden. Empieza por `./encargo ficha`.

## Lo que construyes

Una aplicación en `{app}/`: `main.py` (FastAPI) con **una API pequeña** sobre
SQLite y las mismas pantallas de la maqueta servidas desde `static/`.

1. 🔴 **Lo que se ve no cambia.** Mismas pantallas, misma navegación, mismo
   `estilo.css` (no se toca), y sigue viéndose bien en el teléfono y en la
   PC: `./encargo mirar <url>` te da las dos capturas, mira las dos. Lo que cambia es de dónde salen los datos: donde
   la maqueta usaba `localStorage`, la app llama a tu API (`fetch` a
   `/api/...`). Nada de reescribir la interfaz.
2. **La base es SQLite en `DATOS`** (una variable de entorno; `main.py` ya la
   lee). Las tablas salen de lo que la maqueta guardaba: una por cada cosa que
   se apunta. Crea el esquema al arrancar si no existe (`main.py` tiene el
   hueco). **Empieza vacía**: los datos de ejemplo eran de la maqueta; ella va
   a meter los suyos. Que la primera pantalla vacía diga cómo empezar.
3. **Sólo FastAPI, uvicorn y la librería estándar.** No hay `pip`. Si algo
   falta, no existe. `sqlite3` de la librería estándar, sin ORM.
4. **Nada de acceso ni contraseñas en tu código.** Quien puede entrar lo
   decide el servidor, delante de tu app. No escribas login, sesiones ni
   tokens.
5. **No borres nada de golpe**: borrar una fila es una acción que la maqueta
   ya tiene con su «¿segura?»; conserva eso.
6. 🔴 **Tus manos son `./encargo`, `curl`, y los archivos de `{app}/`.** No
   leas ni busques nada fuera de esta carpeta. Si una orden falla, lee lo que
   dice y sigue. **No uses `rm`**: `./encargo quitar {app}/<archivo>`.

## Cómo lo compruebas (obligatorio antes de decir que está)

1. `./encargo servir` — arranca tu app en local con una base vacía de prueba y
   te dice la URL. Si no arranca, te enseña el error.
2. `curl` contra tu API: crea algo, léelo, cámbialo, bórralo. Y abre las
   páginas: `./encargo mirar <url>` las pinta a 390 px y a 1000 px.
3. Corrige, `./encargo servir` otra vez (reinicia), repite.
4. `./encargo parar` cuando esté, y entonces `./encargo listo`. Se publica
   solo: el hub construye la imagen, la levanta en el servidor y les manda
   la dirección y su acceso a los dos.

No hablas con ella: si te falta algo del plan, `./encargo decir` lo pregunta
a través de quien aprobó.
"""

PRIMER_MENSAJE = """\
Vas a implementar el encargo «{encargo}»: convertir su maqueta en el sistema de
verdad. Lee `INSTRUCCIONES-IMPLEMENTAR.md` de esta carpeta entero antes de
nada, y después `informe.md`.

Empieza por `./encargo ficha`.
"""

# El arranque que se le deja hecho. Lo que importa está decidido aquí y no por
# él: dónde vive la base (DATOS), que las páginas son las de la maqueta, y que
# la salud se consulta sin autenticación desde dentro del contenedor.
MAIN_PY = '''"""Sistema de «{encargo}». Punto de partida generado por el hub; lo completa el implementador."""
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

AQUI = Path(__file__).resolve().parent
# La base vive FUERA del código: en el servidor es un volumen que sobrevive a
# cada despliegue; en local, la carpeta que `./encargo servir` le pase.
DATOS = Path(os.environ.get("DATOS", str(AQUI / "datos-local")))
DATOS.mkdir(parents=True, exist_ok=True)
BASE = DATOS / "app.db"

# Las tablas: una por cada cosa que la maqueta apuntaba. Completar.
ESQUEMA = """
"""


def con() -> sqlite3.Connection:
    c = sqlite3.connect(BASE)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def preparar_base() -> None:
    with con() as c:
        c.executescript(ESQUEMA)


app = FastAPI(title="{encargo}")
preparar_base()


@app.get("/salud")
def salud() -> dict:
    return {{"ok": True}}


# ── La API: aquí van las rutas /api/... ──────────────────────────────────────


# Las pantallas de la maqueta, tal cual. Va al FINAL: lo que no sea /api ni
# /salud es una página o un archivo de static/.
app.mount("/", StaticFiles(directory=AQUI / "static", html=True), name="static")
'''


def app(encargo_id: str) -> Path:
    return encargos.carpeta(encargo_id) / CARPETA_APP


def preparar(con: sqlite3.Connection, encargo_id: str) -> Path:
    """Deja la carpeta lista: contrato, arranque y la maqueta copiada a static/.

    Idempotente sobre lo suyo (el contrato se regenera) y **cuidadoso con lo
    del agente**: `main.py` y `static/` sólo se crean si no existen, porque a
    partir de la segunda ronda ya son su trabajo.
    """
    fila = encargos.ver(con, encargo_id)
    if not fila:
        raise ValueError(f"no hay ningún encargo «{encargo_id}»")
    carpeta = encargos.carpeta(encargo_id)
    destino = app(encargo_id)
    destino.mkdir(parents=True, exist_ok=True)
    sitio = constructor.sitio(encargo_id)
    if not (destino / "static").is_dir():
        if not (sitio / "index.html").is_file():
            raise ValueError(f"«{encargo_id}» no tiene maqueta en sitio/: no hay qué implementar")
        shutil.copytree(sitio, destino / "static")
    if not (destino / "main.py").is_file():
        (destino / "main.py").write_text(MAIN_PY.format(encargo=encargo_id), encoding="utf-8")
    (carpeta / "INSTRUCCIONES-IMPLEMENTAR.md").write_text(
        INSTRUCCIONES.format(encargo=encargo_id, app=CARPETA_APP), encoding="utf-8")
    return destino


def acotar(carpeta: Path) -> None:
    """Como el constructor, más `curl`: es cómo prueba su API sin salirse."""
    from . import agentes, config

    raiz_hub = config.RAIZ_REPO
    conf = carpeta / ".claude"
    conf.mkdir(parents=True, exist_ok=True)
    patron = "//" + str(carpeta).lstrip("/").rstrip("/") + "/**"
    (conf / "settings.json").write_text(
        json.dumps({
            "permissions": {
                "allow": [
                    f"Edit({patron})", f"Read({patron})",
                    "Bash(./encargo:*)", f"Bash({carpeta / 'encargo'}:*)",
                    "Bash(curl:*)",
                ],
                "deny": [
                    f"Read(//{str(raiz_hub).lstrip('/')}/**)",
                    "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)",
                ],
            }
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    agentes._confiar(carpeta)


def primer_mensaje(encargo_id: str) -> str:
    return PRIMER_MENSAJE.format(encargo=encargo_id)


def abrir_agente(con: sqlite3.Connection, encargo_id: str) -> dict:
    """Pone al implementador a trabajar. Sólo sobre algo que toque implementar.

    Dos puertas, y las dos pasan por una persona: la primera vez, «Implementar»
    pulsado por quien aprueba sobre una maqueta publicada (`empezar`); las
    siguientes, un plan de ronda aprobado con el encargo ya en etapa «sistema».
    """
    from . import agentes, api, slots

    fila = encargos.ver(con, encargo_id)
    if not fila:
        raise ValueError(f"no hay ningún encargo «{encargo_id}»")
    if fila["etapa"] != "sistema" or fila["estado"] not in ("aprobado", "implementando"):
        raise ValueError(
            f"«{encargo_id}» está en «{fila['estado']}» (etapa {fila['etapa']}): "
            "implementar sólo empieza con «Implementar» sobre una maqueta publicada, "
            "o con un plan aprobado cuando ya es un sistema")

    carpeta = encargos.carpeta(encargo_id)
    preparar(con, encargo_id)
    acotar(carpeta)
    entrevistador.asegurar_proyecto(con)

    nombre = f"{encargo_id}-implementar"
    slot_id = constructor._slot_llamado(con, nombre)
    if slot_id and (vivo := entrevistador.panel_vivo(con, slot_id)):
        # El estado se asegura también aquí: la primera vez que esto corrió, la
        # ventana abrió y el `tocar` de abajo falló, y el relé volvía a entrar
        # cada vuelta encontrando la ventana viva y el encargo en «aprobado».
        encargos.tocar(con, encargo_id, estado="implementando")
        return {"slot_id": slot_id, "pane_id": vivo["pane_id"],
                **entrevistador.donde_esta(vivo["pane_id"]), "ya_estaba": True}
    if not slot_id:
        slot_id = slots.crear(
            con, entrevistador.PROYECTO, nombre, ruta=str(carpeta),
            nota="Implementador del encargo. Lo abre el hub; no escribas aquí tú.",
        )
    slots.editar(con, slot_id, ruta=str(carpeta), comando=agentes.comando(
        primer_mensaje(encargo_id), modo=MODO))
    pane_id = slots.abrir(con, slot_id, conservar_al_morir=True)
    if not pane_id:
        raise RuntimeError(f"no se pudo abrir la ventana de implementación de «{encargo_id}»")
    entrevistador.comprobar_arranque(pane_id)
    encargos.tocar(con, encargo_id, estado="implementando")
    encargos.registrar(con, "sale", f"abierto el implementador en el panel {pane_id}",
                       encargo_id=encargo_id)
    return {"slot_id": slot_id, "pane_id": pane_id,
            **entrevistador.donde_esta(pane_id), "ya_estaba": False}


def empezar(con: sqlite3.Connection, encargo_id: str) -> dict:
    """«Implementar» sobre una maqueta publicada: la etapa cambia y entra el agente.

    La maqueta se queda en `sitio/` tal cual: es la especificación y hay que
    poder releerla. La URL es la misma; lo que cambia detrás es un contenedor.
    """
    fila = encargos.ver(con, encargo_id)
    if not fila or fila["estado"] != "publicado" or fila["etapa"] != "maqueta":
        raise ValueError(
            f"«{encargo_id}» no es una maqueta publicada: implementar empieza ahí, "
            "cuando ella ya la usó y dijo «así»")
    entrevistador.cerrar_agentes(con, encargo_id)
    encargos.tocar(con, encargo_id, etapa="sistema", estado="aprobado", plan_msg=None)
    encargos.registrar(con, "entra", "implementar: la maqueta pasa a sistema", encargo_id=encargo_id)
    return abrir_agente(con, encargo_id)


def usuario(encargo_id: str) -> str:
    """El nombre de usuario del acceso: el id, que ella ya conoce por la URL."""
    return encargo_id


def generar_acceso(encargo_id: str) -> str:
    """Una contraseña nueva. Devuelve la de verdad UNA vez; en disco queda el hash.

    🔴 Regla dura 5: la contraseña no se guarda. Se manda por el canal en el
    momento de publicar y no vuelve a verse; lo que viaja al servidor es el
    hash con el que Caddy la comprueba. Si se pierde, se genera otra.
    """
    import bcrypt

    clave = secrets.token_urlsafe(9)
    hash_ = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    (encargos.carpeta(encargo_id) / ACCESO).write_text(hash_ + "\n", encoding="utf-8")
    return clave


def tiene_acceso(encargo_id: str) -> bool:
    return (encargos.carpeta(encargo_id) / ACCESO).is_file()
