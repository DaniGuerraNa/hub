"""Lanzar agentes de Claude Code desde la UI.

El hub no ejecuta el agente: abre una ventana de tmux donde corre `claude` con
un prompt inicial. El trabajo sigue pasando donde siempre, y tú lo ves en la
terminal embebida.

Nunca se usa `send-keys` (decisión 22): inyectar teclas en una shell cuyo estado
se desconoce ejecuta comandos reales con consecuencias reales.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path

from . import api, config, registry, tmux

# Un nombre de sesión de tmux no admite cualquier cosa; se deriva del id.
_NO_VALIDO = re.compile(r"[^\w.\-]+")


class GuardrailBloqueado(PermissionError):
    """El proyecto declara `never`: no se lanza nada, aunque lo pida la UI."""


def sesion_para(con: sqlite3.Connection, proyecto_id: str) -> str:
    """Dónde abrir la ventana: donde ya vive ese proyecto, si es que vive."""
    for panel in api.paneles_abiertos(con):
        if panel["proyecto_id"] == proyecto_id:
            return panel["session"]
    return _NO_VALIDO.sub("-", proyecto_id) or "hub-agentes"


def comando(prompt: str) -> str:
    """`claude` con un prompt inicial. Sin `-p`: queremos sesión interactiva."""
    return f"claude {shlex.quote(prompt)}"


def lanzar(
    con: sqlite3.Connection,
    proyecto_id: str,
    prompt: str,
    nombre_ventana: str = "agente",
    ruta: str | None = None,
) -> dict:
    """Abre la ventana y devuelve dónde quedó, para que la UI navegue allí."""
    proyecto = api.obtener_proyecto(con, proyecto_id)
    if not proyecto:
        raise ValueError(f"proyecto desconocido: {proyecto_id}")

    # `claude ''` abre una sesión con un argumento vacío en vez de fallar, así
    # que la ventana se crearía y nadie sabría por qué el agente no hace nada.
    if not prompt.strip():
        raise ValueError("hace falta un prompt: sin él la ventana se abre sin encargo")

    # `never` significa nunca, aunque la petición venga de la propia UI:
    # primero se cambia el guardrail en projects.yml (regla dura 7).
    if proyecto["guardrail"] == "never":
        raise GuardrailBloqueado(
            f"«{proyecto['nombre']}» tiene guardrail `never`. "
            "Cámbialo en projects.yml si de verdad quieres lanzar agentes ahí."
        )

    destino = ruta or proyecto["asiento"]
    if not destino:
        raise ValueError(f"«{proyecto['nombre']}» no tiene asiento donde abrir la ventana")

    session = sesion_para(con, proyecto_id)
    # El PATH de usuario, o el agente arranca sin las herramientas del usuario:
    # `hub-web` corre bajo systemd y su PATH no trae `~/.local/bin`.
    entorno = {"PATH": tmux.path_de_usuario()}
    if not tmux.existe_sesion(session):
        tmux.nueva_sesion(session, destino, entorno=entorno)

    indice = tmux.nueva_ventana(session, destino, nombre_ventana[:40], comando(prompt),
                                entorno)
    return {"session": session, "ventana": indice, "ruta": destino}


# ─────────────────────── crear un proyecto desde el chat ───────────────────
#
# El reparto, y es lo que hace que esto sea seguro sin pedirle permisos al
# asistente:
#
#   El hub   crea la carpeta VACÍA, la acota con permisos y da el alta en su
#            propio registro. Nada de eso toca un repo ajeno.
#   El agente rellena el proyecto, dentro de esa carpeta y sólo dentro.
#
# El asistente sigue siendo de sólo lectura: no escribe nada de esto. Pide, y el
# hub lanza. Así los permisos no dependen de qué proyecto se esté hablando en
# mitad de una conversación, que era lo que hacía frágil la otra vía.

_ID_VALIDO = re.compile(r"[a-z0-9][a-z0-9-]*")


class CarpetaOcupada(FileExistsError):
    """La ruta ya tiene contenido: no es un proyecto en blanco."""


def _acotar_permisos(destino: Path) -> None:
    """Deja al agente escribir en su carpeta y en ninguna otra.

    🔴 Tres cosas que se pagaron midiéndolas, y que parecen detalles:

    1. `Edit(ruta)` y NO `Write(ruta)`. Las reglas de ruta sólo se evalúan para
       `Edit`, que cubre todas las herramientas de edición; un `Write(ruta)` se
       ignora y el agente acaba pidiendo permiso para todo.
    2. La ruta absoluta necesita `//` delante. Sin la doble barra el patrón no
       casa con nada y no avisa: parecería concedido y no lo estaría.
    3. `hasTrustDialogAccepted`. Un workspace sin confiar **descarta el `allow`
       entero**, así que sin esto el agente arrancaría sin ninguno de sus
       permisos en una máquina recién instalada.
    """
    conf = destino / ".claude"
    conf.mkdir(parents=True, exist_ok=True)
    patron = "//" + str(destino).lstrip("/").rstrip("/") + "/**"

    # 🔴 Y LEER las skills y semillas del hub. Salió probándolo de verdad: el
    # agente arrancaba, leía «usa la skill nuevo-proyecto», no la encontraba
    # —vive en el repo del hub y él corre en la carpeta nueva— y se ponía a
    # rastrear `~/.claude/skills/` pidiendo permisos. El prompt mandaba usar
    # algo que el agente no podía ver.
    #
    # Lectura y sólo lectura, y sólo de esas dos carpetas: es lo que necesita
    # para seguir el procedimiento y aplicar la capa base.
    hub = str(config.RAIZ_REPO).lstrip("/").rstrip("/")
    (conf / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        f"Edit({patron})",
                        f"Read(//{hub}/.claude/skills/**)",
                        f"Read(//{hub}/semillas/**)",
                        # El gestor de kits, que sólo consulta: `listar` y
                        # `ruta`. Sin esto el agente se queda pidiendo permiso
                        # en mitad del procedimiento que se le acaba de mandar
                        # seguir. Y poder LEERLO antes de ejecutarlo, que es lo
                        # que hace por su cuenta y es buena costumbre.
                        f"Bash(bash {config.RAIZ_REPO}/scripts/kit.sh:*)",
                        f"Read(//{hub}/scripts/**)",
                    ],
                    # Y hasta aquí. La lista cubre el procedimiento entero; lo
                    # que se salga de él se PREGUNTA, con el usuario mirando la
                    # ventana. Perseguir cada permiso hasta que no pregunte
                    # nunca sería confundir «no molesta» con «está acotado»: la
                    # pregunta es la última señal de que algo se sale del guion.
                    # Fuera de su carpeta no escribe. No está en `deny` a
                    # propósito: si de verdad hace falta tocar algo de fuera,
                    # que lo pregunte y lo apruebe un humano — `deny` ni
                    # siquiera deja llegar la pregunta.
                    "deny": [],
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _confiar(destino)


def _confiar(destino: Path) -> None:
    """Marca la carpeta como de confianza en `~/.claude.json`.

    Sin esto Claude Code ignora las entradas de `allow` del proyecto —lo dice
    por stderr y sigue— y el agente se queda pidiendo permiso para cada archivo
    de su propia carpeta.
    """
    conf = Path.home() / ".claude.json"
    try:
        datos = json.loads(conf.read_text(encoding="utf-8")) if conf.exists() else {}
    except (OSError, json.JSONDecodeError):
        # No poder marcar la confianza no impide crear el proyecto: el agente
        # pedirá permiso y el usuario lo dará. Romper `~/.claude.json` sí sería
        # grave, así que ante la duda no se toca.
        return
    proyectos = datos.setdefault("projects", {})
    if not isinstance(proyectos, dict):
        return
    proyectos.setdefault(str(destino), {})["hasTrustDialogAccepted"] = True
    tmp = conf.with_suffix(".json.hub-tmp")
    try:
        tmp.write_text(json.dumps(datos), encoding="utf-8")
        tmp.replace(conf)   # atómico: nunca se queda a medias
    except OSError:
        tmp.unlink(missing_ok=True)


def crear_proyecto(
    con: sqlite3.Connection,
    id_proyecto: str,
    nombre: str,
    ruta: str,
    dominio: str = "personal",
    guardrail: str = "ask",
    estado_ref: str = "ESTADO.md",
    rutas: list[str] | None = None,
) -> dict:
    """Crea la carpeta, la acota, da el alta y lanza al agente a rellenarla.

    `rutas` son repos que YA EXISTEN y que no se tocan: se declaran para que el
    hub los mida —commits sin respaldo, ramas, worktrees— y nada más. Es el
    patrón del asiento de orquestación: una carpeta nueva donde vive la
    estructura del hub, y el código donde ya estaba.

    🔴 Sirve para repos que no se pueden modificar, y esa garantía no la da esta
    función: la da `_acotar_permisos`, que acota al agente a la carpeta creada.
    Lo que se declara aquí queda FUERA de ese permiso, así que es medible y no
    escribible — que es justo lo que se quiere.
    """
    id_proyecto = (id_proyecto or "").strip()
    nombre = (nombre or "").strip()
    if not _ID_VALIDO.fullmatch(id_proyecto):
        raise ValueError(
            f"«{id_proyecto}» no sirve como id: minúsculas, números y guiones."
            " El id no se puede cambiar después."
        )
    if not nombre:
        raise ValueError("hace falta un nombre.")
    if dominio not in ("personal", "laboral"):
        raise ValueError("el dominio es `personal` o `laboral`.")
    if guardrail not in ("auto", "ask", "never"):
        raise ValueError("el guardrail es `auto`, `ask` o `never`.")

    destino = Path(ruta).expanduser()
    if not destino.is_absolute():
        raise ValueError(f"la ruta tiene que ser absoluta: «{ruta}»")

    # 🔴 «Una carpeta en blanco no tiene nada que perder» es cierto — pero es una
    # garantía que hay que COMPROBAR, no suponer. Una ruta mal escrita apuntando
    # a algo que ya existe es justo el caso en que dar permisos amplios duele, y
    # es el error más fácil de cometer dictando una ruta por chat.
    if destino.exists() and any(destino.iterdir()):
        raise CarpetaOcupada(
            f"«{destino}» ya tiene contenido. Para eso está «anexa mi proyecto»,"
            " que registra lo que ya existe sin tocarlo."
        )

    if api.obtener_proyecto(con, id_proyecto):
        raise ValueError(f"ya hay un proyecto con el id «{id_proyecto}».")

    # 🔴 Se comprueba que existan, y no es puntillismo: lo que se declara SE MIDE,
    # y medir sobre una carpeta inexistente no da error, da un cero. Un cero en
    # «commits sin respaldo» se lee como «está todo a salvo», así que una ruta
    # mal escrita aquí produce exactamente la tranquilidad falsa que el hub
    # existe para evitar.
    apuntadas: list[str] = []
    for cruda in (rutas or []):
        cruda = str(cruda).strip()
        if not cruda:
            continue
        camino = Path(cruda).expanduser()
        if not camino.is_absolute():
            raise ValueError(f"la ruta tiene que ser absoluta: «{cruda}»")
        if not camino.is_dir():
            raise ValueError(
                f"«{camino}» no existe o no es una carpeta. Lo que se declara se"
                " mide, y medir sobre algo que no está da un cero que parece"
                " «no hay nada sin respaldar»."
            )
        apuntadas.append(str(camino))

    destino.mkdir(parents=True, exist_ok=True)
    # Con git desde el minuto uno: el hub mide commits sin respaldo, y un
    # proyecto sin git es invisible para esa medición.
    subprocess.run(["git", "init", "-b", "main"], cwd=destino,
                   capture_output=True, check=False)
    _acotar_permisos(destino)

    # El alta la hace el hub: `projects.yml` es su registro. Si el agente tuviera
    # que escribirlo, necesitaría permiso fuera de su carpeta.
    registry.añadir_proyecto({
        "id": id_proyecto, "nombre": nombre, "dominio": dominio,
        "asiento": str(destino), "estado_ref": estado_ref,
        "guardrail": guardrail, "status": "activo", "rutas": apuntadas,
    })
    proyectos = registry.cargar()
    registry.sincronizar(con, proyectos)

    # 🔴 El guardrail se comprueba DESPUÉS de crear, y el fallo no se propaga.
    # Salió probándolo: con `never` la llamada devolvía error mientras el
    # proyecto quedaba creado y dado de alta — el usuario veía «bloqueado» y no
    # se enteraba de que ya existía. Crear la identidad es legítimo con
    # cualquier guardrail; lo que `never` prohíbe es poner a trabajar a un
    # agente dentro. Así que se crea, no se lanza, y se DICE.
    try:
        lanzado = lanzar(
            con, id_proyecto, _PROMPT_NUEVO.format(
                nombre=nombre, id=id_proyecto, ruta=destino, estado_ref=estado_ref,
            skill=config.RAIZ_REPO / '.claude' / 'skills' / 'nuevo-proyecto' / 'SKILL.md',
            hub=config.RAIZ_REPO,
            apuntadas=_texto_apuntadas(apuntadas),
            ),
            nombre_ventana="nuevo-proyecto", ruta=str(destino),
        )
    except GuardrailBloqueado as exc:
        return {
            "id": id_proyecto, "ruta": str(destino), "agente": False,
            "aviso": f"{exc} El proyecto está creado y registrado, pero vacío:"
                     " tendrás que montarlo tú o cambiar el guardrail.",
        }
    return {"id": id_proyecto, "ruta": str(destino), "agente": True, **lanzado}


def _texto_apuntadas(rutas: list[str]) -> str:
    """El párrafo del prompt que nombra los repos declarados, si los hay.

    🔴 Decírselo importa tanto como acotarle el permiso. El agente que ve un
    proyecto «vacío» cuyo código está en otra parte tiende a proponer moverlo o
    clonarlo ahí — que es exactamente lo que no se puede hacer cuando esos repos
    son de otro equipo. Que lo lea evita la propuesta, no sólo el destrozo.
    """
    if not rutas:
        return ""
    lista = "\n".join(f"    - {r}" for r in rutas)
    return (
        "\nEste proyecto se orquesta desde esta carpeta, pero SU CÓDIGO VIVE"
        " FUERA, en repos que ya existen y que están declarados en el hub para"
        f" medirlos:\n\n{lista}\n\n"
        "🔴 Esos repos son de SÓLO LECTURA para ti, y no por una limitación"
        " técnica que haya que rodear: puede que sean de otro equipo o que no se"
        " puedan tocar. No escribas en ellos, no los muevas, no los clones aquí y"
        " no propongas reorganizarlos. Toda la estructura del hub —capa base,"
        " kits, documento de estado— va en ESTA carpeta, y desde aquí se apunta a"
        " ellos. Si crees que hace falta tocar alguno, dilo y para.\n"
    )


# El encargo. No repite la skill `nuevo-proyecto`: la INVOCA, para que no haya
# dos versiones del procedimiento que se separen con el tiempo. Y le dice qué
# está hecho ya, o el agente volvería a preguntar lo que el usuario acaba de
# contestar en el chat.
_PROMPT_NUEVO = """\
Lee y sigue este procedimiento para terminar de montar este proyecto:

    {skill}

Es la skill `nuevo-proyecto` del hub. No la tienes cargada como skill porque
corres en la carpeta del proyecto y ella vive en la del hub: léela con Read, que
para eso tienes permiso. No la copies aquí.

El hub está en {hub}. Todo lo que necesitas de allí, con la ruta hecha — úsalas
tal cual en vez de buscar, que es lo único que tienes permiso para tocar fuera:

    bash {hub}/scripts/kit.sh listar        # qué kits hay y qué aporta cada uno
    bash {hub}/scripts/kit.sh ruta base     # dónde está la semilla de la capa base

Ya está hecho, NO lo repitas ni lo preguntes:
- La carpeta existe y tiene `git init` (rama main): {ruta}
- El alta en el registro del hub: id `{id}`, nombre «{nombre}», estado_ref `{estado_ref}`
{apuntadas}

Te toca, dentro de ESTA carpeta y sólo dentro:
1. Aplicar la capa base y rellenar sus marcadores.
2. Crear `{estado_ref}` vacío pero con su forma: qué estado tiene, qué hacer al
   volver, qué está bloqueado.
3. Enseñar qué kits hay y qué aporta cada uno, y dejar elegir. No apliques
   ninguno por tu cuenta.
4. Un primer commit.

Si algo te pide escribir fuera de esta carpeta, para y dilo: no tienes permiso ahí
y es a propósito.
"""


# --------------------------------------------------------------------------- #
# Kits
# --------------------------------------------------------------------------- #

# 🔴 Las dos líneas de la semilla que el hub sí rellena, y sólo esas dos.
#
# `semillas/kit/kit.yml` trae `id: mi-kit` y `nombre: Mi kit` como valores de
# EJEMPLO —no marcadores `@ASI@`, porque `@` no puede abrir un escalar plano en
# YAML y la plantilla no parseaba—. Copiarla tal cual dejaba un kit recién
# creado llamándose `mi-kit`: el segundo que hicieras chocaba con el primero, y
# el choque aparecía mucho después, al medirlo.
#
# Se anclan al principio de línea a propósito. Un reemplazo del texto suelto
# tocaría también los comentarios que explican por qué son valores de ejemplo, y
# el archivo dejaría de contar su propio porqué.
_ID_SEMILLA = re.compile(r"^id: mi-kit$", re.MULTILINE)
_NOMBRE_SEMILLA = re.compile(r"^nombre: Mi kit$", re.MULTILINE)


def crear_kit(
    con: sqlite3.Connection,
    id_kit: str,
    nombre: str,
    ruta: str,
    guardrail: str = "ask",
) -> dict:
    """Crea el repo de un kit desde la semilla y lanza al agente que lo diseña.

    Mismo reparto que `crear_proyecto`, y por el mismo motivo: el hub pone la
    carpeta, la semilla y el alta —cosas suyas—, y el contenido lo escribe un
    agente dentro de esa carpeta y sólo dentro.

    🔴 El kit se crea en SU PROPIO REPO, nunca dentro de
    `~/.local/share/hub/kits/<id>/<versión>/`. Esa otra carpeta es el repositorio
    local de instalación, con la versión en la ruta —el equivalente de `~/.m2`—:
    escribir ahí hace que `kit.sh instalar` vea la carpeta, se cortocircuite y
    responda `✓ instalado` sin haber clonado ni resuelto ningún tag. Un éxito que
    no ocurrió.
    """
    id_kit = (id_kit or "").strip()
    nombre = (nombre or "").strip()
    if not _ID_VALIDO.fullmatch(id_kit):
        raise ValueError(
            f"«{id_kit}» no sirve como id de kit: minúsculas, números y guiones."
            " El id no se puede cambiar después: es como lo referencian sus"
            " consumidores."
        )
    if not nombre:
        raise ValueError("hace falta un nombre.")
    if guardrail not in ("auto", "ask", "never"):
        raise ValueError("el guardrail es `auto`, `ask` o `never`.")

    destino = Path(ruta).expanduser()
    if not destino.is_absolute():
        raise ValueError(f"la ruta tiene que ser absoluta: «{ruta}»")
    if destino.exists() and any(destino.iterdir()):
        raise CarpetaOcupada(
            f"«{destino}» ya tiene contenido. Un kit nace vacío, desde la"
            " semilla: extraerlo de un proyecto que ya lo tenía produce una"
            " copia de ese proyecto, con sus rutas y su stack dentro."
        )
    if api.obtener_proyecto(con, id_kit):
        raise ValueError(f"ya hay un proyecto o kit con el id «{id_kit}».")

    semilla = config.RAIZ_REPO / "semillas" / "kit"
    if not (semilla / "kit.yml").is_file():
        raise RuntimeError(f"no encuentro la semilla de kit en {semilla}")

    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(semilla, destino, dirs_exist_ok=True)

    manifiesto = destino / "kit.yml"
    texto = manifiesto.read_text(encoding="utf-8")
    texto = _ID_SEMILLA.sub(f"id: {id_kit}", texto, count=1)
    texto = _NOMBRE_SEMILLA.sub(f"nombre: {nombre}", texto, count=1)
    manifiesto.write_text(texto, encoding="utf-8")

    subprocess.run(["git", "init", "-b", "main"], cwd=destino,
                   capture_output=True, check=False)
    _acotar_permisos(destino)

    registry.añadir_proyecto({
        "id": id_kit, "nombre": nombre, "tipo": "kit", "dominio": "personal",
        "asiento": str(destino), "estado_ref": "CHANGELOG.md",
        "guardrail": guardrail, "status": "activo",
    })
    registry.sincronizar(con, registry.cargar())

    # Mismo orden que en `crear_proyecto`, y por el mismo fallo medido: con
    # `never` el kit queda creado y registrado, y decirlo evita que el usuario
    # crea que no ha pasado nada.
    try:
        lanzado = lanzar(
            con, id_kit, _PROMPT_KIT.format(
                nombre=nombre, id=id_kit, ruta=destino,
                skill=config.RAIZ_REPO / ".claude" / "skills" / "nuevo-kit" / "SKILL.md",
                hub=config.RAIZ_REPO,
            ),
            nombre_ventana="nuevo-kit", ruta=str(destino),
        )
    except GuardrailBloqueado as exc:
        return {
            "id": id_kit, "ruta": str(destino), "agente": False,
            "aviso": f"{exc} El kit está creado y registrado, con la semilla"
                     " dentro, pero sin diseñar: tendrás que montarlo tú o"
                     " cambiar el guardrail.",
        }
    return {"id": id_kit, "ruta": str(destino), "agente": True, **lanzado}


# Igual que `_PROMPT_NUEVO`: INVOCA la skill en vez de repetirla, para que no
# haya dos versiones del procedimiento separándose con el tiempo.
_PROMPT_KIT = """\
Lee y sigue este procedimiento para diseñar este kit:

    {skill}

Es la skill `nuevo-kit` del hub. No la tienes cargada como skill porque corres
en la carpeta del kit y ella vive en la del hub: léela con Read, que para eso
tienes permiso. No la copies aquí.

El hub está en {hub}:

    bash {hub}/scripts/kit.sh listar        # qué kits hay ya, para no duplicar
    bash {hub}/scripts/kit.sh verificar {id}   # comprueba este manifiesto

Ya está hecho, NO lo repitas ni lo preguntes:
- La carpeta existe, con la semilla dentro y `git init` (rama main): {ruta}
- `kit.yml` ya tiene su `id` (`{id}`) y su `nombre` («{nombre}») puestos
- El alta en el registro del hub, con `tipo: kit`

Te toca, dentro de ESTA carpeta y sólo dentro. Empieza por el paso 1 de la
skill, que son las cuatro preguntas: PREGÚNTALAS antes de escribir nada, porque
de la primera —qué capacidad aporta, en una frase que empiece por un verbo— sale
todo lo demás.

Después, rellena el manifiesto: `descripcion`, `expone`, `consume`, `requiere` y
`aplica` con el modo de cada archivo. Y las notas de mantenimiento.

🔴 Dos cosas que la skill explica y que no puedes saltarte:
- Una plantilla que nombra el proyecto que la originó no es una plantilla, es
  una copia. Si aquí acaba una ruta, un stack o un concepto de un proyecto
  concreto, el segundo consumidor tendrá que reescribirlo entero.
- Un kit no se da por bueno hasta verlo acertar Y verlo fallar. Aplicarlo a un
  consumidor real, romper un archivo a propósito, comprobar que la deriva lo
  marca, restaurarlo y comprobar que vuelve. Un verde que nadie ha visto en rojo
  no es evidencia.

Si algo te pide escribir fuera de esta carpeta, para y dilo: no tienes permiso
ahí y es a propósito.
"""
