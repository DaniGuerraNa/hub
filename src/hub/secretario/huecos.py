"""Lo que el secretario no supo hacer, de hueco a mejora y de vuelta (C-0252).

El recorrido: `no_se_hacer` apunta el hueco en la bitácora (C-0247); con el sí
del dueño se apunta como idea del tablero, marcada con `ideas.MARCA_HUECO`;
alguien la toma y nace su ficha, que al cerrarse `hecha` declara en su
cabecera qué herramientas lo resuelven (`resuelve:`, `fichas.resuelve`). Aquí
se cruzan las tres cosas, una sola vez: Confianza lo pinta (`mejoras`, por
`api.secretario_huecos`) y el ciclo de `hub-secretario` le dice al dueño que
ya sabe hacerlo (`recoger`). Lee por `ideas` y `fichas`; sólo escribe en su
propia memoria.

🔴 **No es un aviso ni un asunto** (regla dura 3, decisión 379): «ya sé hacer
X» se dice una vez en el chat y nunca sale al teléfono. Por eso este módulo no
importa `avisos` ni `asuntos`, y la frase se arma aquí, sin el modelo (lo
comprueba un test sobre el árbol del módulo).

🔴 **Sólo se dice lo comprobable** (regla dura 13): «hecha en una copia de
trabajo» no es «cargada en el servicio que corre». Se dice si cada
herramienta que declara la ficha está en `herramientas.todas()` de este
proceso; si falta una, se calla y se vuelve a mirar en la vuelta siguiente.
"""

from __future__ import annotations

import re
import sqlite3

from . import conversacion, memoria, misdatos, piezas

#: Cómo lee el dueño el estado de la ficha y, si aún no la hay, el de la idea.
_ESTADO_FICHA = {"en-curso": "en curso"}
_ESTADO_IDEA = {"nueva": "en el tablero", "tomada": "tomada", "descartada": "descartada"}

#: Las ideas cuyo «ya sé» ya se dijo, en `estado` de la memoria. Por idea y no
#: por texto: si el mismo hueco vuelve a apuntarse y a resolverse, es noticia.
CLAVE = "huecos_resueltos"


def _recorridos(sin: frozenset[int] = frozenset()) -> dict[str, tuple[dict, dict | None]]:
    """Cada hueco que el dueño convirtió en mejora, por su `ideas.clave_hueco`:
    su idea y, si ya la tomaron, la cabecera de su ficha. Sin carpeta de
    fichas —quien instala el producto no las tiene—, sin ficha.

    `sin`: ideas que no hacen falta. El ciclo pasa las ya dichas, para no
    leer las fichas en cada vuelta por algo que ya contó (regla dura 14)."""
    from .. import db, fichas, ideas

    try:
        h = db.conectar()
        try:
            por_hueco = {c: i for c, i in ideas.de_huecos(h).items() if i["id"] not in sin}
        finally:
            h.close()
    except sqlite3.Error:
        return {}
    if not por_hueco:
        return {}
    carpeta = piezas.carpeta_de_fichas()
    por_id = {}
    if carpeta and carpeta.is_dir() and any(i["estado"] == "tomada" for i in por_hueco.values()):
        por_id = {str(f.get("id")): f for f in fichas.listar(carpeta)}
    out = {}
    for clave, i in por_hueco.items():
        m = re.search(r"C-\d+", i.get("ref") or "")
        out[clave] = (i, por_id.get(m.group(0)) if m else None)
    return out


def mejoras() -> dict[str, dict]:
    """El recorrido de cada hueco convertido en mejora, como lo pinta
    Confianza: su idea, su ficha si la hay y una etiqueta para el dueño."""
    out = {}
    for clave, (i, f) in _recorridos().items():
        if f:
            estado = f.get("estado") or ""
            etiqueta = _ESTADO_FICHA.get(estado, estado)
        else:
            etiqueta = _ESTADO_IDEA.get(i["estado"], i["estado"])
        out[clave] = {"idea": i["id"], "estado_idea": i["estado"], "ref": i.get("ref") or "",
                      "ficha": {"id": f.get("id"), "estado": f.get("estado")} if f else None,
                      "etiqueta": "apuntado como mejora · " + etiqueta}
    return out


def _frase(hueco: str, idea: int, ficha: str) -> str:
    # Por guion y no por el modelo: es una frase fija sobre hechos comprobados,
    # y lo que dijera un modelo no lo comprobaría nadie antes de salir.
    return (f"Ya sé hacer algo que me pediste y no sabía: «{hueco}». La mejora que apuntamos "
            f"(idea {idea}, ficha {ficha}) está hecha y ya la tengo cargada: pídemelo cuando quieras.")


def recoger(con: sqlite3.Connection) -> int:
    """Dice en el chat, una vez, cada hueco que ya sabe hacer. Devuelve cuántos.

    Lo llama el ciclo de `hub-secretario` (`servicio.una_vuelta`) en su
    `_paso`. Cuenta un hueco cuya idea se tomó, cuya ficha está `hecha` y
    cuyas herramientas (`resuelve`) están todas en este proceso. Sin carpeta
    de fichas —el producto no trae `cambios/`— devuelve 0 sin mirar nada."""
    from .. import db, fichas, ideas

    if piezas.carpeta_de_fichas() is None:
        return 0
    dichos = [int(x) for x in memoria.leer(con, CLAVE) or [] if isinstance(x, int)]
    listos = [(i, f) for i, f in _recorridos(frozenset(dichos)).values()
              if f and i["estado"] == "tomada" and f.get("estado") == "hecha" and fichas.resuelve(f)]
    if not listos:
        return 0
    from . import herramientas
    # Con el dueño: el ciclo no tiene hilo, y sin él `todas()` esconde lo que
    # sólo se hace con él delante (404), que también existe. Lo que ahora no
    # está disponible (C-0408) cuenta como que no existe.
    hay = herramientas.todas(con_el_dueno=True)
    dichas = 0
    for i, f in listos:
        nombres = fichas.resuelve(f)
        if any(n not in hay for n in nombres):
            continue
        hueco = " ".join(ideas.hueco_de(i).split())
        # El hueco lo redactó un modelo con lo que dijo el dueño: sus datos se
        # tapan, que el turno y la bitácora van a `memoria.db` y se copian (382).
        texto = misdatos.tapar(_frase(hueco, i["id"], str(f.get("id"))))
        params = misdatos.tapar({"que": hueco, "idea": i["id"], "ficha": str(f.get("id")), "resuelve": nombres})
        dichos.append(i["id"])
        # El turno, su apunte y la marca de dicho, juntos: un fallo a medias
        # no lo repite ni lo pierde.
        with db.transaccion(con):
            conversacion.decir(con, None, texto)
            memoria.apuntar(con, "hueco_resuelto", params=params, resultado="dicho en el chat")
            memoria.poner(con, CLAVE, dichos)
        dichas += 1
    return dichas
