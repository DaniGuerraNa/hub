"""Qué ventanas hay que volver a abrir después de un corte, y de qué muestra.

Todo lo de aquí es **decisión, no ejecución**: qué muestra sirve de fuente, qué
ruta le toca a cada ventana y qué comando se le deja escrito. No toca tmux, así
que se puede probar entero sin abrir una sola ventana — que es justo lo que la
versión anterior no permitía, porque la decisión vivía mezclada con la ejecución
dentro de `slots.restaurar`.

Vive aparte de `slots` por la dirección de las dependencias: `slots` importa
`api`, así que `api` no puede importar `slots` (decisión 197). La pantalla
necesita enseñar el plan antes de ejecutarlo, o sea que `api` tiene que poder
calcularlo. Los dos importan esto y nadie importa a nadie al revés.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

# Es una ventana de trabajo suya, no un agente del hub, así que le toca el
# modelo: hereda el que él tenga puesto en su propia configuración.
COMANDO_SUGERIDO = "claude --dangerously-skip-permissions"


# 🔴 Lista blanca, y no el valor de la muestra tal cual. `panel.comando` es lo
# que tmux reportaba como proceso en primer plano, y de ahí a escribirlo en una
# terminal hay un salto que no se da: lo que se escribe son cadenas fijas
# elegidas aquí, nunca texto que venga de la base. Lo que no esté en este mapa
# abre la ventana en su ruta y no escribe nada — que es la mitad del valor y la
# mitad que nunca puede hacer daño.
#
# `node`, `npm` y `bash` se quedan fuera A PROPÓSITO: un `npm run dev` no se
# reconstruye desde el nombre del proceso, y adivinarlo sería peor que dejar la
# ventana lista para que él escriba lo suyo.
COMANDOS_CONOCIDOS = {
    # modelo: hereda — lo mismo que arriba; el comando va entero desde ahí.
    "claude": COMANDO_SUGERIDO,
    "codex": "codex",
}

# Cuando WSL pierde la conexión con el disco de Windows, mueve el montaje roto a
# un lado —`/mnt/c_stale`, `/mnt/c_stale2`…— y monta uno nuevo en `/mnt/c`. Los
# procesos que estaban dentro se quedan con la ruta vieja, y el muestreo la
# guarda tal cual la ve.
#
# Medido el 2026-09-16 sobre la muestra del corte: **10 de 19 rutas guardadas ya
# no existían**, casi todas por esto. Restaurar sin arreglarlo abriría media
# sesión en directorios que no están, y `tmux` falla ahí. Los dos directorios
# huérfanos de esta máquina son del 13-sep, con un minuto entre uno y otro.
_RANCIA = re.compile(r"^/mnt/([a-z])_stale\d*(?=/|$)")
# Y la otra forma que apareció en la misma muestra: la ruta de Windows sin el
# prefijo del montaje, `/Users/...` en vez de `/mnt/c/Users/...`.
_SIN_MONTAJE = re.compile(r"^/Users/")


def normalizar_ruta(cwd: str) -> str:
    """La ruta guardada, traída al montaje de hoy. No comprueba que exista."""
    if not cwd:
        return cwd
    arreglada = _RANCIA.sub(r"/mnt/\1", cwd)
    if arreglada == cwd:
        arreglada = _SIN_MONTAJE.sub("/mnt/c/Users/", cwd)
    return arreglada


def marcados_para_restaurar(con: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in con.execute(
        "SELECT * FROM slot WHERE status='activo' AND restaurar=1 ORDER BY proyecto_id, id"
    )]


def candidatos_de_restauracion(con: sqlite3.Connection, limite: int = 6) -> list[dict]:
    """Las muestras entre las que se puede elegir, la más reciente primero.

    🔴 Existe porque **ninguna regla automática las distingue**, y eso se
    descubrió probando con los datos de verdad. El 16-sep quedaron dos muestras
    marcadas «antes de un corte» a cuatro horas una de otra: la buena, con el
    escritorio de trabajo, y otra de un tmux que vivió veinte segundos mientras
    él arreglaba las cosas a mano. Las dos con `preservado=1`, las dos con trece
    paneles, y las dos **con los mismos slots** —porque `reconciliar_bindings`
    reatachó los vínculos a las ventanas nuevas por (sesión, ventana, panel),
    que es lo que tiene que hacer—.

    Inventar un criterio («la que tenga más agentes», «la que no esté en casa»)
    habría sido adivinar con cara de saber. Se enseñan y elige él, que es además
    lo que dice el principio 9.
    """
    filas = con.execute(
        """SELECT s.id, s.tomado_en,
                  COUNT(DISTINCT p.session || ':' || p.window_idx) AS ventanas,
                  COUNT(DISTINCT CASE WHEN p.slot_id IS NOT NULL
                                      THEN p.session || ':' || p.window_idx END) AS con_slot
           FROM snapshot s JOIN panel p ON p.snapshot_id = s.id
           WHERE s.preservado IN (1, 2)
           GROUP BY s.id HAVING con_slot > 0
           ORDER BY s.id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    salida = []
    for f in filas:
        # Un par de rutas y los procesos que había: es lo que deja reconocer
        # «ésta es mi escritorio de la mañana» frente a «ésta es la de después».
        detalle = con.execute(
            """SELECT DISTINCT comando FROM panel
               WHERE snapshot_id=? AND comando<>'' ORDER BY comando""",
            (f["id"],),
        ).fetchall()
        salida.append({
            "id": f["id"], "tomado_en": f["tomado_en"],
            "ventanas": f["ventanas"], "con_slot": f["con_slot"],
            "procesos": [d["comando"] for d in detalle],
        })
    return salida


def _muestra_anterior(con: sqlite3.Connection, pid_actual: int | None = None) -> int | None:
    """La muestra por defecto: la más reciente de las marcadas antes de un corte.

    Es sólo un **defecto**, no una deducción: la pantalla enseña cuál eligió y
    deja cambiarla (`candidatos_de_restauracion`). Tras un apagón normal hay un
    solo corte y una sola candidata, y entonces acierta sin que nadie mire.

    Lo que se descartó, y por qué, porque las dos parecían buenas ideas:

    - **«La más reciente que tenga paneles con slot».** Probada contra los datos
      del 16-sep: elegía la de ese mismo día con tmux ya levantado a mano —trece
      ventanas en el directorio de casa con shells desnudas— y habría
      reproducido el destrozo en vez de deshacerlo. Con datos inventados habría
      dado verde.
    - **«La última del PID de tmux anterior».** Mejor señal, y también falla: el
      PID había cambiado dos veces ese día, así que «el anterior» era el tmux de
      veinte segundos y no el escritorio de la mañana.
    """
    candidatos = candidatos_de_restauracion(con, limite=1)
    return candidatos[0]["id"] if candidatos else None


def plan_de_restauracion(con: sqlite3.Connection, existe=None,
                         muestra_id: int | None = None) -> list[dict]:
    """Qué ventanas habría que abrir para dejarlo como estaba. No abre ninguna.

    Separado de `restaurar()` porque es donde está toda la decisión —qué muestra,
    qué rutas, qué comandos— y nada de ello necesita tmux para probarse. La
    versión anterior tenía la decisión mezclada con la ejecución y sólo se podía
    probar abriendo ventanas de verdad.

    `existe` se inyecta para poder probar rutas muertas sin fabricarlas en disco.
    """
    existe = existe or (lambda r: Path(r).is_dir())
    marcados = {s["id"]: s for s in marcados_para_restaurar(con)}
    if not marcados:
        return []

    plan: list[dict] = []
    con_ventana: set[int] = set()
    vistas: set[tuple] = set()

    muestra = muestra_id or _muestra_anterior(con, None)
    if muestra is not None:
        for f in con.execute(
            """SELECT * FROM panel WHERE snapshot_id=? AND slot_id IS NOT NULL
               ORDER BY session, window_idx, pane_idx""",
            (muestra,),
        ):
            slot = marcados.get(f["slot_id"])
            if slot is None:
                continue
            # 🔴 Una entrada por VENTANA, no por panel: dos paneles con el mismo
            # `window_idx` son una ventana partida en dos, y restaurarlos como
            # dos ventanas multiplicaría el escritorio en cada apagón. La
            # división en sí no se reconstruye: es geometría, no trabajo.
            clave = (f["session"], f["window_idx"])
            if clave in vistas:
                continue
            vistas.add(clave)
            con_ventana.add(slot["id"])
            plan.append(_entrada(slot, f["cwd"], COMANDOS_CONOCIDOS.get(f["comando"], ""),
                                 "muestra", existe))

    # Un slot marcado que no salía en la muestra —cerrado antes del corte, o
    # creado después— sigue recibiendo su ventana en su ruta. Es el contrato de
    # la decisión 165, que esto amplía y no sustituye.
    for slot in marcados.values():
        if slot["id"] not in con_ventana:
            plan.append(_entrada(slot, slot["ruta"],
                                 slot["comando"] or COMANDO_SUGERIDO, "slot", existe))
    return plan


def es_refugio(ruta: str) -> bool:
    """Si esa ruta no es un destino, sino donde cae una shell sin destino.

    🔴 La tercera forma de ruta rota, y la única que **existe**, así que las dos
    comprobaciones de abajo la daban por buena. Medido el 2026-09-17 en su
    máquina: tras el apagón, WSL renombró el montaje a `/mnt/c_stale2`,
    tmux-resurrect guardó esa ruta y al restaurar tmux cayó a `$HOME` porque el
    directorio ya no estaba. De las cinco ventanas de `work`, las cuatro con la
    ruta rancia acabaron en `~` y la única con la ruta buena acabó donde debía.

    Lo que lo vuelve asunto del hub es que **se propaga**: el plan lee el estado
    de AHORA, así que sin esto «Restaurar» volvería a abrir en `~` —10 de 14
    ventanas el día que se midió— y cada vuelta lo dejaría igual de mal.
    """
    return ruta in ("/", os.path.expanduser("~"))


def _entrada(slot: dict, cwd: str | None, comando: str, origen: str, existe) -> dict:
    """Una ventana del plan, con la ruta ya resuelta y su porqué si no se pudo."""
    pedida = normalizar_ruta(cwd or "")
    # La del slot: es donde el contrato viejo habría abierto de todos modos.
    respaldo = normalizar_ruta(slot["ruta"] or "")
    ruta, aviso = pedida, ""

    if pedida and es_refugio(pedida) and respaldo != pedida and existe(respaldo):
        ruta = respaldo
        aviso = (f"la ventana estaba en «{pedida}», que es donde cae una shell "
                 "sin ruta; se abre en la del slot")
    elif not pedida or not existe(pedida):
        if respaldo and existe(respaldo):
            ruta = respaldo
            aviso = (f"«{pedida}» ya no existe; se abre en la ruta del slot")
        else:
            ruta = ""
            aviso = f"«{pedida or 'sin ruta'}» ya no existe y el slot no tiene otra"
    return {"slot_id": slot["id"], "nombre": slot["nombre"],
            "proyecto_id": slot["proyecto_id"], "ruta": ruta,
            "ruta_pedida": pedida, "comando": comando if ruta else "",
            "origen": origen, "aviso": aviso}


