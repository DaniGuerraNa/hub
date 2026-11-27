"""Comandos preparados: plantillas con huecos que se escriben en una ventana nueva.

Nació de una frase suya sobre el viaje: *«para lanzar comandos con presets…
son sólo `git clone`, sólo es agregar el nombre del repo al final, y un comando
por ambiente»*. Desde el móvil, escribir a mano una orden larga con una URL
dentro es justo lo que no se puede hacer; elegirla de una lista y rellenar un
hueco, sí.

🔴 **Aquí no vive ningún secreto, ni siquiera de paso** (regla dura 5). Una
plantilla es texto que se guarda en `comandos.yml` y que cualquiera que abra el
hub puede leer, así que lo que lleva credenciales **no es la plantilla: es un
script suyo**, fuera del repo y con permisos 600, al que la plantilla sólo
apunta. El hub queda igual que con el token de Telegram — sabe dónde está, no
qué es.

🔴 **Y no se ejecuta nada.** Lo que hace el hub es abrir una ventana de tmux en
la carpeta y **dejar el comando escrito, sin Enter** — el tercer caso de la
regla dura 15, el mismo que usa «Restaurar» (decisión 164). Esa media pulsación
que falta es el gate humano del principio 6, y es lo que permite que el
navegador de archivos siga sin ejecutar nada (decisión 203) y por tanto sin
vivir detrás del interruptor de la terminal.

Los huecos se escriben `{repo}` y se rellenan con `shlex.quote`: una plantilla
es texto del usuario, y interpolarlo en crudo sería ejecución arbitraria en
cuanto un nombre de repo llevara un `;` (regla dura 10).

**Una lista de valores** (C-0507, decisión 464): «pásale una lista de repos y
que los clone». `preparar_lote` rellena la misma plantilla con cada valor, y
`dejar_escrito` los deja escritos en UNA línea unida por ` ; ` (nunca con
saltos: `abrir_en` pega antes de que la shell pida el bracketed paste, y cada
salto sería un Enter). 🔴 **Y aquí sí se ejecuta, pero sólo esto**:
`ejecutar_lote`, que llama únicamente `hub-secretario` con el sí del dueño a
las órdenes exactas, sobre un comando que ÉL marcó `ejecutable: true` en su
`comandos.yml` —el hub no escribe nunca ese archivo— y que declara qué
carpeta crea (`crea: "{repo}"`), para saltarse lo que ya estaba y comprobar
lo que salió.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import sqlite3
import subprocess
from pathlib import Path

from . import config

ARCHIVO = "comandos.yml"

# Un hueco es `{nombre}` con letras, números y guiones. Sin llaves anidadas ni
# expresiones: esto es una plantilla, no un lenguaje.
HUECO = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_-]*)\}")


#: Cuántas órdenes de una vez (C-0507): una lista más larga es otra cosa que
#: una tanda de repos, y cada una puede tardar `TOPE_S`.
TOPE_LOTE = 30
#: Lo que puede tardar cada orden ejecutada (`ejecutar_lote`).
TOPE_S = 300
#: Lo que se guarda de la salida de cada orden: el final, que es donde está el error.
SALIDA_MAX = 600

# Lo que no puede llevar un valor de una lista: un carácter de control
# escrito en una shell es una tecla, no un nombre (C-0428).
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Una URL con usuario y contraseña dentro (`https://u:clave@host`): git la
# repite en sus errores tal como la recibió.
_CREDENCIAL_EN_URL = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)


class ComandoInvalido(ValueError):
    """Lo que impide escribir una orden a medias en un panel."""


class CarpetaInvalida(ValueError):
    """La carpeta donde se quería abrir la ventana o correr la orden no vale:
    fuera de lo que el hub indexa, no es una carpeta, o su proyecto no deja."""


class VentanaNoAbierta(RuntimeError):
    """tmux no abrió la ventana o no se vio la orden escrita (regla dura 21)."""


def archivo() -> Path:
    """Dónde viven. Función y no constante, por lo mismo que en `acceso`: el
    archivo puede aparecer después de que el proceso arranque."""
    declarado = os.environ.get("HUB_COMANDOS_YML")
    return Path(declarado) if declarado else config.HUB_HOME / ARCHIVO


def leer() -> list[dict]:
    """Los comandos declarados. Sin archivo, ninguno — no es un error."""
    ruta = archivo()
    if not ruta.exists():
        return []
    datos = config.leer_yaml(ruta.read_text(encoding="utf-8")) or {}
    comandos = datos.get("comandos") or []
    return [c for c in comandos if isinstance(c, dict) and c.get("id") and c.get("plantilla")]


def por_id(id_comando: str) -> dict | None:
    return next((c for c in leer() if c["id"] == id_comando), None)


def huecos(plantilla: str) -> list[str]:
    """Qué hay que rellenar, en el orden en que aparece. Sin repetidos."""
    vistos: list[str] = []
    for nombre in HUECO.findall(plantilla):
        if nombre not in vistos:
            vistos.append(nombre)
    return vistos


def expandir(plantilla: str, valores: dict[str, str]) -> str:
    """La orden lista para escribirla, con cada valor escapado.

    🔴 Falta un hueco y no se escribe nada: una orden a medias pegada en un
    panel es peor que ninguna — se queda ahí, a la vista, esperando un Enter que
    la ejecutaría mal. Es el mismo criterio de «Restaurar» (decisión 164).
    """
    faltan = [h for h in huecos(plantilla) if not (valores.get(h) or "").strip()]
    if faltan:
        raise ComandoInvalido("falta " + ", ".join(f"«{h}»" for h in faltan))

    def sustituir(coincidencia: re.Match) -> str:
        return shlex.quote(valores[coincidencia.group(1)].strip())

    return HUECO.sub(sustituir, plantilla)


def preparar(id_comando: str, valores: dict[str, str], ruta: str) -> str:
    """La orden de un comando declarado, lista para dejarla escrita en `ruta`.

    `valores` puede traer de más: se usan los huecos que tenga la plantilla.
    `{ruta}` lo rellena la carpeta si no viene escrito, porque es el dato que
    el móvil no puede teclear y el que da sentido a todo esto. Un comando que
    no existe o un hueco vacío levantan `ComandoInvalido`, y no se escribe nada.
    """
    comando = por_id(id_comando)
    if not comando:
        raise ComandoInvalido(f"no hay ningún comando «{id_comando}»")
    usados = {h: str(valores.get(h) or "") for h in huecos(comando["plantilla"])}
    if not usados.get("ruta", "").strip():
        usados["ruta"] = str(ruta)
    return expandir(comando["plantilla"], usados)


# ── Listas de valores (C-0507, decisión 464) ─────────────────────────────────


def validar_valor(valor) -> str:
    """Un valor de una lista, limpio, o `ComandoInvalido`.

    Además del `shlex.quote` de siempre: sin caracteres de control, sin `-`
    al principio —un script que pasa el valor a `git` lo leería como una
    opción— y sin `..` —el valor también da nombre a la carpeta que se crea
    (`crea`), y con `..` saldría de ella—."""
    v = str(valor if valor is not None else "").strip()
    if not v:
        raise ComandoInvalido("hay un valor vacío")
    if _CONTROL.search(v):
        raise ComandoInvalido(f"«{_CONTROL.sub('?', v)}» lleva caracteres de control")
    if v.startswith("-"):
        raise ComandoInvalido(f"«{v}» empieza por «-»: se leería como una opción")
    if ".." in v:
        raise ComandoInvalido(f"«{v}» lleva «..»")
    return v


def _comando(id_comando: str) -> dict:
    comando = por_id(id_comando)
    if not comando:
        raise ComandoInvalido(f"no hay ningún comando «{id_comando}»")
    return comando


def hueco_de_lista(id_comando: str, hueco: str | None = None, fijos: dict | None = None) -> str:
    """Qué hueco rellena cada valor de la lista: el que se pida o, si no se
    pide, el único de la plantilla que no es `{ruta}` ni viene en `fijos`."""
    plantilla = _comando(id_comando)["plantilla"]
    if hueco:
        if hueco not in huecos(plantilla) or hueco == "ruta":
            raise ComandoInvalido(f"«{id_comando}» no tiene el hueco «{hueco}»")
        return hueco
    libres = [h for h in huecos(plantilla) if h != "ruta" and h not in (fijos or {})]
    if len(libres) != 1:
        raise ComandoInvalido(f"«{id_comando}» tiene {len(libres)} huecos por rellenar "
                              f"({', '.join(libres) or 'ninguno'}): di cuál lleva la lista")
    return libres[0]


def _valores(valores) -> list[str]:
    if isinstance(valores, str):
        valores = [valores]
    lista: list[str] = []
    for v in valores or []:
        v = validar_valor(v)
        if v not in lista:
            lista.append(v)
    if not lista:
        raise ComandoInvalido("la lista está vacía")
    if len(lista) > TOPE_LOTE:
        raise ComandoInvalido(f"son {len(lista)}: como mucho {TOPE_LOTE} de una vez")
    return lista


def ordenes(id_comando: str, hueco: str | None, valores, ruta: str,
            fijos: dict | None = None) -> list[tuple[str, str, Path | None]]:
    """`(valor, orden, carpeta que crea o None)` de cada valor, o `ComandoInvalido`
    si falla cualquiera: una lista a medias no se escribe ni se corre. Es
    `preparar_lote` con la carpeta de `crea` al lado, para quien tiene que
    saltar lo que ya está o enseñarlo antes de pedir el sí."""
    fijos = {str(k): validar_valor(v) for k, v in (fijos or {}).items()}
    nombre = hueco_de_lista(id_comando, hueco, fijos)
    salida = []
    for v in _valores(valores):
        usados = {**fijos, nombre: v}
        salida.append((v, preparar(id_comando, usados, ruta), crea(id_comando, usados, ruta)))
    return salida


def preparar_lote(id_comando: str, hueco: str | None, valores, ruta: str,
                  fijos: dict | None = None) -> list[str]:
    """La orden de cada valor de `valores` en el hueco `hueco` (o el único que
    hay), con `fijos` en los demás. `ComandoInvalido` si falla cualquiera —un
    valor con control, `-` delante o `..`, un hueco que falta— o si son más
    de `TOPE_LOTE`. Los repetidos cuentan una vez."""
    return [orden for _, orden, _ in ordenes(id_comando, hueco, valores, ruta, fijos)]


def crea(id_comando: str, valores: dict, ruta: str) -> Path | None:
    """La carpeta que crea esa orden, según el campo `crea` del comando
    (`crea: "{repo}"`, relativo a `ruta`), o None si no lo declara.

    Lo escribe el dueño en `comandos.yml` junto a la plantilla: el hub no
    adivina qué crea un script suyo. Sin ese campo no se salta nada ni se
    puede comprobar que salió, y quien lo usa lo dice."""
    patron = _comando(id_comando).get("crea")
    if not patron:
        return None
    patron = str(patron)
    if "ruta" in huecos(patron):
        raise ComandoInvalido("`crea` es relativo a la carpeta: no lleva {ruta}")
    usados = {h: validar_valor(valores.get(h)) for h in huecos(patron)}
    relativa = HUECO.sub(lambda m: usados[m.group(1)], patron)
    base = Path(ruta).expanduser().resolve()
    destino = base / relativa
    if Path(relativa).is_absolute() or destino.resolve() == base or not destino.resolve().is_relative_to(base):
        raise ComandoInvalido(f"`crea` de «{id_comando}» sale de la carpeta: {relativa}")
    return destino


def carpeta_para(con: sqlite3.Connection, ruta: str, *, respetar_never: bool) -> tuple[Path, str | None]:
    """La carpeta resuelta contra el confín del navegador (`api.confin`, el
    único) y el proyecto al que pertenece. `CarpetaInvalida` si no vale."""
    from . import api, navegador, registry

    try:
        destino = navegador.resolver(ruta, api.confin(con))
    except (navegador.FueraDeRaiz, navegador.NoNavegable) as exc:
        raise CarpetaInvalida(str(exc)) from None
    if not destino.is_dir():
        raise CarpetaInvalida("sólo se puede abrir una terminal en una carpeta")
    proyecto_id = registry.atribuidor(con).atribuir(str(destino))
    if respetar_never and proyecto_id:
        proyecto = api.obtener_proyecto(con, proyecto_id) or {}
        # Regla dura 7: `never` es nunca, aunque lo pida él; primero se cambia el guardrail.
        if proyecto.get("guardrail") == "never":
            raise CarpetaInvalida(f"esa carpeta es de «{proyecto.get('nombre') or proyecto_id}», que tiene "
                                  "guardrail `never`: ahí no se prepara ni se corre nada")
    return destino, proyecto_id


def dejar_escrito(con: sqlite3.Connection, id_comando: str, valores, ruta: str, *,
                  hueco: str | None = None, fijos: dict | None = None,
                  respetar_never: bool = False) -> dict:
    """Abre una ventana de tmux en `ruta` con la orden escrita y SIN Enter.

    Es lo que hacía `/archivos/terminal` (decisiones 164, 203 y 251), sacado
    aquí para que lo use también el secretario (C-0507). `valores`:

    - un `dict` de huecos (el formulario de Archivos): una orden, como siempre;
    - una lista de valores para el hueco `hueco` (o el único): una orden por
      valor, **en una sola línea unida por ` ; `**. 🔴 Nunca con saltos de
      línea: `abrir_en` pega en una shell recién nacida, antes de que pida el
      bracketed paste, y cada salto llegaría como un Enter
      (`tmux.pegar_en_panel`, `slots.abrir_en`). Con `crea` en el comando,
      los que ya tienen su carpeta se saltan y se dice cuáles; sin `crea`, no
      se salta ninguno y también se dice (`sin_crea`).

    Sin `id_comando`, sólo la ventana. `respetar_never`: se niega si la
    carpeta es de un proyecto con guardrail `never` (lo pide el secretario;
    Archivos no lo miraba y sigue igual). Errores: `CarpetaInvalida`,
    `ComandoInvalido` (no se abre nada) y `VentanaNoAbierta`.

    Devuelve `session`, `ventana` (o None si tmux no la dice), `pane_id`,
    `texto`, `ruta`, `saltados`, `sin_crea` y `url` (la de /trabajo)."""
    from urllib.parse import quote

    from . import slots, tmux

    destino, proyecto_id = carpeta_para(con, ruta, respetar_never=respetar_never)
    texto, saltados, sin_crea = "", [], False
    if id_comando and isinstance(valores, dict):
        texto = preparar(id_comando, valores, str(destino))
    elif id_comando:
        lote = ordenes(id_comando, hueco, valores, str(destino), fijos)
        sin_crea = any(carpeta is None for _, _, carpeta in lote)
        saltados = [v for v, _, carpeta in lote if carpeta is not None and carpeta.exists()]
        quedan = [orden for v, orden, _ in lote if v not in saltados]
        if not quedan:
            raise ComandoInvalido("ya estaban todos: " + ", ".join(saltados))
        texto = " ; ".join(quedan)
        if "\n" in texto or "\r" in texto:
            raise ComandoInvalido("la plantilla tiene saltos de línea: en una lista, cada uno sería un Enter")

    session = slots.sesion_para(con, proyecto_id) if proyecto_id else "hub"
    try:
        pane_id = slots.abrir_en(str(destino), destino.name or "archivos", session, texto)
    except Exception as exc:  # noqa: BLE001 — se dice en voz alta (regla 21)
        raise VentanaNoAbierta(str(exc)) from exc
    try:
        ventana = next((p["window_idx"] for p in tmux.listar_paneles() if p["pane_id"] == pane_id), None)
    except Exception as exc:  # noqa: BLE001 — la ventana ya está abierta: sin su número, se dice y se sigue
        print(f"[comandos] no supe el número de la ventana de {pane_id}: {exc}", flush=True)
        ventana = None
    url = f"/trabajo?session={quote(session)}" + (f"&ventana={ventana}" if ventana is not None else "")
    return {"session": session, "ventana": ventana, "pane_id": pane_id, "texto": texto, "ruta": str(destino),
            "saltados": saltados, "sin_crea": sin_crea, "url": url}


def _recortar(salida: str) -> str:
    """El final de la salida, sin credenciales en las URL. Es una red, no una
    garantía (regla dura 22): quien la lleve al modelo la pasa además por
    `secretario.memoria.ocultar_secretos`."""
    salida = _CREDENCIAL_EN_URL.sub(r"\1[oculto]@", salida or "").strip()
    return salida[-SALIDA_MAX:]


def _correr(orden: str, carpeta: Path, tope_s: float) -> tuple[int | None, str]:
    """Una orden con `bash -c` en `carpeta`: el PATH de usuario por `env`
    (regla dura 18: `hub-secretario` corre bajo systemd), sin terminal a la
    que preguntar (`GIT_TERMINAL_PROMPT=0`, stdin cerrado) y con tope. Si se
    pasa, se mata su grupo entero: `git` es hijo del script, no de la shell.
    Devuelve el código (None si se cortó) y la salida."""
    from . import tmux

    proc = subprocess.Popen(
        ["env", f"PATH={tmux.path_de_usuario()}", "GIT_TERMINAL_PROMPT=0", "bash", "-c", orden],
        cwd=str(carpeta), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Su grupo propio, para matarlo entero al pasarse; no para que
        # sobreviva al servicio (eso es `procesos.desasir`, 344).
        text=True, errors="replace", process_group=0)
    try:
        salida, _ = proc.communicate(timeout=tope_s)
        return proc.returncode, salida
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            salida, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            # Algo que salió del grupo sigue con la salida abierta: no se le
            # espera, que este hilo también atiende resúmenes e investigaciones.
            proc.kill()
            if proc.stdout:
                proc.stdout.close()
            salida = ""
        return None, salida


def _es_repo_creado(carpeta: Path) -> str | None:
    """None si en `carpeta` hay un repo de git propio; si no, por qué no.

    🔴 `rev-parse --show-toplevel` comparado con la carpeta, y no sólo
    `--git-dir`: donde se clona suele estar dentro de otro repo, y `--git-dir`
    contestaría el de arriba aunque el clon no hubiera dejado nada."""
    if not carpeta.is_dir():
        return "no se creó la carpeta"
    try:
        r = subprocess.run(["git", "-C", str(carpeta), "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"no pude preguntarle a git: {exc}"
    if r.returncode != 0 or Path(r.stdout.strip()).resolve() != carpeta.resolve():
        return "la carpeta está, pero no es un repo de git"
    return None


def ejecutar_lote(con: sqlite3.Connection, id_comando: str, valores, ruta: str, *,
                  hueco: str | None = None, fijos: dict | None = None, tope_s: float = TOPE_S,
                  aprobadas: list[str] | None = None) -> dict:
    """Corre la orden de cada valor, de una en una, y comprueba lo que creó.

    🔴 **Sólo la llama `hub-secretario`, desde su cola** (`secretario.lotes`),
    después de que el dueño aprobara en Pendientes las órdenes exactas
    (C-0507, decisión 464). Nunca `hub-web` ni un panel de tmux. Y sólo:

    - un comando con `ejecutable: true` en `comandos.yml`, que escribe el
      dueño y nunca el código del hub; la plantilla tampoco sale del modelo;
    - con `crea` declarado: sin saber qué carpeta crea no se puede saltar lo
      que ya estaba ni comprobar que salió (regla dura 17);
    - en una carpeta del confín, fuera de un proyecto con guardrail `never`.

    `aprobadas`: las órdenes que él vio y aprobó. Si las de ahora no son
    ésas —cambió `comandos.yml` mientras la lista esperaba en la cola—, no
    se corre ninguna: correría algo que no aprobó.

    Lo que ya tiene su carpeta se salta («ya estaba») y nunca se entra en
    ella; si esa carpeta no es un repo, se dice (`aviso`). Lo demás va con
    `bash -c` en la carpeta (`_correr`), con tope de `tope_s`, y se da por
    hecho si su carpeta es un repo de git (`_es_repo_creado`), no por el
    código de salida.

    Devuelve `ruta` y `resultados`: por valor, `estado` (`hecho`, `ya_estaba`
    o `fallo`), su `orden` y, si se corrió, `codigo`, `salida` (recortada,
    `_recortar`) y, si falló, `error`."""
    comando = _comando(id_comando)
    if comando.get("ejecutable") is not True:
        raise ComandoInvalido(f"«{id_comando}» no está marcado `ejecutable: true` en comandos.yml: "
                              "eso lo decide el dueño en su archivo")
    if not comando.get("crea"):
        raise ComandoInvalido(f"«{id_comando}» no dice qué carpeta crea (`crea` en comandos.yml): "
                              "sin eso no puedo saltar lo que ya está ni comprobar que salió")
    destino, _ = carpeta_para(con, ruta, respetar_never=True)
    lote = ordenes(id_comando, hueco, valores, str(destino), fijos)
    if aprobadas is not None and [orden for _, orden, _ in lote] != list(aprobadas):
        raise ComandoInvalido("las órdenes ya no son las que aprobó (cambió comandos.yml desde entonces): "
                              "no corrí ninguna")
    resultados = []
    for valor, orden, carpeta in lote:
        if carpeta.exists() or carpeta.is_symlink():
            r = {"valor": valor, "orden": orden, "estado": "ya_estaba"}
            # Una carpeta a medias (un tope, un reinicio) también «está»: no se
            # toca, pero no se da por clonada sin decirlo.
            if _es_repo_creado(carpeta):
                r["aviso"] = "la carpeta está, pero no es un repo de git"
            resultados.append(r)
            continue
        try:
            codigo, salida = _correr(orden, destino, tope_s)
        except OSError as exc:
            codigo, salida = -1, f"no se pudo lanzar: {exc}"
        fallo = _es_repo_creado(carpeta)
        if codigo is None:
            # Lo que quedó a medias no se borra (el hub no borra nada suyo):
            # se dice, porque la próxima vez saldría como «ya estaba».
            fallo = f"tardó más de {tope_s:g} s y se cortó" + (
                "; dejó su carpeta a medias: mírala antes de repetirlo" if carpeta.exists() else "")
        r = {"valor": valor, "orden": orden, "estado": "fallo" if fallo else "hecho", "codigo": codigo,
             "salida": _recortar(salida)}
        if fallo:
            r["error"] = fallo + (f" (salió con {codigo})" if codigo not in (0, None) else "")
        resultados.append(r)
    return {"ruta": str(destino), "resultados": resultados}
