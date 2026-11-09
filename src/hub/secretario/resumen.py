"""El resumen del día, armado por script (decisión 308).

Qué hay hoy en la agenda, qué venció, qué toca hoy, qué espera el sí del dueño
y qué se anotó desde ayer. Todo eso es una consulta, no una interpretación:
pasarlo por un modelo costaría cuota cada mañana para decir lo mismo con otras
palabras, y podría equivocarse en una fecha. El modelo sólo entra si el dueño
pide algo que sí la necesita (un disparador con `pide`).

Con `noche=True` es el parte de la mañana (decisión 360): delante, lo que
espera de él; luego el día; luego lo que pasó y lo que falló en las últimas
24 horas —el mismo «desde ayer» de las notas, no otra noche inventada—. Sólo
hechos y lo que le espera: «llevas N días sin…» es gestión y sigue prohibido
(regla dura 3). Se lee en el teléfono: secciones cortas, una línea por cosa, y
la que no tiene nada no aparece.

Lo que espera de él no se calcula aquí: sale de `asuntos.reunir` (decisión
380), el mismo sitio del que lo lee su pantalla. Sólo las clases que el parte
ya decía (`asuntos.DEL_PARTE`): su primera línea va al teléfono, y las
sugerencias no salen de la pantalla (379).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import agenda, asuntos, memoria, tiempo

TOPE = 5
#: Cuántas sesiones se miran como mucho; si se llega, la cifra lo dice.
SESIONES = 60


def _hora(iso: str | None) -> str:
    if not iso or len(iso) == 10:
        return "todo el día"
    # La idea de hora local del hub entero (C-0051): una hora sin zona es de
    # la casa, no de la máquina (C-0185).
    return tiempo.a_local(iso, "%H:%M")


def _eventos_de_hoy(hoy: datetime, fallos: list[str] | None = None) -> list[dict] | None:
    """Los de hoy, o None si no hay agenda conectada (no es lo mismo que «nada»).

    Si está conectada y no se puede leer, el porqué va a `fallos`: el parte lo
    dice; el resumen de siempre sale igual sin ella."""
    try:
        if agenda.disponible():
            return None
        return agenda.eventos(hoy, hoy + timedelta(days=1))
    except Exception as exc:  # noqa: BLE001 — sin agenda el resumen sale igual, y lo dice
        if fallos is not None:
            fallos.append(str(exc))
        return None


def del_dia(con: sqlite3.Connection, ahora: datetime | None = None, *, noche: bool = False) -> str:
    ahora = ahora or tiempo.ahora_local()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_hoy_utc = (hoy + timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    ahora_utc = ahora.astimezone(timezone.utc).isoformat(timespec="seconds")
    dia: list[str] = []

    sin_agenda: list[str] = []
    eventos = _eventos_de_hoy(hoy, sin_agenda)
    if eventos:
        dia.append("Agenda:\n" + "\n".join(f"· {_hora(e['inicio'])} {e['titulo']}" for e in eventos[:8]))
    elif eventos is not None:
        dia.append("Agenda: nada hoy.")

    abiertos = memoria.compromisos(con, "abierto")
    vencidos = [c for c in abiertos if c.get("vence") and c["vence"] < ahora_utc]
    de_hoy = [c for c in abiertos if c not in vencidos
              and ((c.get("vence") and c["vence"] < fin_hoy_utc) or (c.get("recordar_en") and c["recordar_en"] < fin_hoy_utc))]
    if de_hoy:
        dia.append("Para hoy:\n" + "\n".join(
            f"· {c['que']}" + (f" ({_hora(c.get('recordar_en') or c.get('vence'))})") for c in de_hoy[:TOPE]))
    if vencidos:
        extra = f" (y {len(vencidos) - TOPE} más)" if len(vencidos) > TOPE else ""
        dia.append(f"Vencidos: {len(vencidos)}{extra}\n" + "\n".join(f"· {c['que']}" for c in vencidos[:TOPE]))

    # Lo que espera de él, de su dueño en vivo (380). Sin noche, sólo cuántos
    # permisos: es lo único de eso que dice el resumen de siempre.
    try:
        espera = asuntos.reunir(con, clases=asuntos.DEL_PARTE if noche else ("permiso",), momento=ahora)
    except Exception as exc:  # noqa: BLE001 — sin sus marcas no se sabe qué calló: se dice y sigue
        espera = asuntos.Reunidos(fallos=[f"No pude leer lo que te espera: {_corto(exc)}"])
    pendientes = sum(a.clase == "permiso" for a in espera.asuntos)
    desde_utc = (ahora - timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    nuevas = [dict(f) for f in con.execute("SELECT texto FROM nota WHERE creada >= ? ORDER BY id DESC", (desde_utc,))]

    if noche:
        p = _Parte()
        for porque in sin_agenda:
            p.fallo(1, f"· No pude leer la agenda: {_corto(porque)}")
        texto = _parte(con, p, ahora, desde_utc, dia, espera, nuevas,
                       para_hoy=len(eventos or []) + len(de_hoy), vencidos=len(vencidos))
    else:
        partes = list(dia)
        if pendientes:
            partes.append(f"Esperan tu sí: {pendientes}.")
        if nuevas:
            partes.append(f"Anotado desde ayer: {len(nuevas)}\n" + "\n".join(
                f"· {n['texto'][:140]}" for n in nuevas[:3]))
        # Sin los permisos no se sabe si alguno espera: se dice (regla dura 21).
        partes += [f"{porque}." for porque in espera.fallos]
        texto = "\n\n".join(partes) if partes else "Nada pendiente para hoy."
    # Las notas, los fallos y lo que pide el orquestador traen texto de otros.
    # Tapa las llaves que reconoce; es una red, no una garantía (regla dura 22).
    return memoria.ocultar_secretos(texto)


# ───────────────────────────── el parte (decisión 360) ─────────────────────────────


#: La misma que corta las líneas de los asuntos: dos copias divergen.
_corto = asuntos.corto


def _s(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


@dataclass
class _Cosa:
    n: int
    uno: str
    varios: str
    linea: str


class _Parte:
    """Lo que se va leyendo. Cada cosa que espera o falla lleva su cuenta: la
    primera línea, que es la que llega al teléfono, suma ésas y no las líneas
    (una línea puede ser 37 fichas, regla dura 13)."""

    def __init__(self) -> None:
        self.espera: list[_Cosa] = []
        self.paso: list[str] = []
        self.fallos: list[_Cosa] = []

    def espera_(self, n: int, uno: str, varios: str, linea: str) -> None:
        self.espera.append(_Cosa(n, uno, varios, linea))

    def fallo(self, n: int, linea: str) -> None:
        # Lo que espera (de `asuntos`) y lo que pasó (de aquí) se leen de la
        # misma fuente por dos sitios: si no se puede leer, los dos lo dicen
        # con la misma línea, y es un fallo, no dos (regla dura 13).
        if any(c.linea == linea for c in self.fallos):
            return
        self.fallos.append(_Cosa(n, "fallo", "fallos", linea))

    def titular_espera(self) -> str:
        juntas: dict[tuple[str, str], int] = {}
        for c in self.espera:
            juntas[(c.uno, c.varios)] = juntas.get((c.uno, c.varios), 0) + c.n
        cosas = [_s(n, uno, varios) for (uno, varios), n in juntas.items()]
        lista = cosas[0] if len(cosas) == 1 else ", ".join(cosas[:-1]) + " y " + cosas[-1]
        return ("Te espera " if len(cosas) == 1 and sum(juntas.values()) == 1 else "Te esperan ") + lista


def _te_espera(p: _Parte, r: asuntos.Reunidos, ahora: datetime) -> None:
    """Las líneas de «Te espera», de los asuntos: cada clase junta en una
    línea lo que es lo mismo, y la cuenta de cosas va aparte (la primera línea
    suma cosas, no líneas)."""
    def de(clase: str, tipo: str | None = None) -> list[asuntos.Asunto]:
        return [a for a in r.asuntos if a.clase == clase and (tipo is None or a.tipo == tipo)]

    if n := len(de("permiso")):
        p.espera_(n, "permiso", "permisos", f"· {_s(n, 'permiso espera', 'permisos esperan')} tu sí")
    for a in de("orquestador"):
        if a.tipo == "pregunta":
            p.espera_(1, "pregunta del orquestador", "preguntas del orquestador", f"· {a.texto}")
        else:
            p.espera_(1, "confirmación del orquestador", "confirmaciones del orquestador", f"· {a.texto}")
    if n := len(de("sesion")):
        p.espera_(n, "sesión que pregunta", "sesiones que preguntan",
                  f"· {_s(n, 'sesión te pregunta', 'sesiones te preguntan')} algo en /trabajo")
    if n := len(de("canal", "pregunta")):
        p.espera_(n, "pregunta del canal", "preguntas del canal",
                  f"· {_s(n, 'pregunta de tus sesiones', 'preguntas de tus sesiones')} sin contestar en /canal")
    if n := len(de("canal", "sin-destino")):
        p.espera_(n, "respuesta del canal", "respuestas del canal",
                  f"· {_s(n, 'respuesta', 'respuestas')} del canal sin sesión a la que volver, en /canal")
    if suyas := de("ficha"):
        ayer = (ahora - timedelta(days=1)).date().isoformat()
        nuevas_suyas = sum(1 for a in suyas if a.fecha >= ayer)
        p.espera_(len(suyas), "ficha", "fichas",
                  f"· {_s(len(suyas), 'ficha espera', 'fichas esperan')} algo tuyo"
                  + (f" ({nuevas_suyas} desde ayer)" if nuevas_suyas else "") + ":\n"
                  + "\n".join(f"  {a.origen} {_corto(a.detalle, 70)}" for a in suyas[:3]))


def _parte(con: sqlite3.Connection, p: _Parte, ahora: datetime, desde: str, dia: list[str],
           espera: asuntos.Reunidos, nuevas: list[dict], para_hoy: int, vencidos: int) -> str:
    _te_espera(p, espera, ahora)
    for porque in espera.fallos:
        p.fallo(1, f"· {porque}")

    def notas() -> None:
        for n in nuevas[:3]:
            p.paso.append(f"· Anoté: «{_corto(n['texto'])}»")
        if len(nuevas) > 3:
            p.paso.append(f"· y {_s(len(nuevas) - 3, 'nota más', 'notas más')}")

    # Cada lectura en su propio try (regla dura 14): que el orquestador no se
    # pueda leer no deja al dueño sin el resto del parte, y se le dice. El
    # orden es el de cada sección: lo que más pesa, antes.
    for nombre, leer in (("el orquestador", lambda: _del_orquestador(p, desde)),
                         ("las sesiones de Claude", lambda: _de_las_sesiones(p, desde)),
                         ("los avisos del hub", lambda: _de_los_avisos(p, desde)),
                         ("la salud del equipo", lambda: _de_la_salud(p)),
                         ("lo que hice", lambda: _de_la_memoria(con, p, desde)),
                         ("las notas", notas),
                         ("las fichas", lambda: _de_las_fichas(p, ahora))):
        try:
            leer()
        except Exception as exc:  # noqa: BLE001 — se dice en el parte, no tumba el parte
            p.fallo(1, f"· No pude leer {nombre}: {_corto(exc)}")

    titular = []
    if p.espera:
        titular.append(p.titular_espera())
    if para_hoy:
        titular.append(f"{para_hoy} para hoy")
    if vencidos:
        titular.append(_s(vencidos, "vencido", "vencidos"))
    if p.fallos:
        titular.append(_s(sum(c.n for c in p.fallos), "fallo", "fallos"))
    if not (titular or p.paso):
        return "Noche tranquila: nada pasó, nada falló y nada te espera."
    bloques = [" · ".join(titular) if titular else "Nada te espera ni falló de noche."]
    if p.espera:
        bloques.append("Te espera:\n" + "\n".join(c.linea for c in p.espera))
    bloques += dia
    if p.paso:
        bloques.append("De noche:\n" + "\n".join(p.paso))
    if p.fallos:
        bloques.append("Falló:\n" + "\n".join(c.linea for c in p.fallos))
    return "\n\n".join(bloques)


def _nombre_accion(accion: str) -> str:
    from . import piezas
    a = piezas.acciones().get(accion)
    nombre = (a.nombre if a and a.nombre else accion.replace("_", " "))
    return nombre[:1].lower() + nombre[1:]


def _de_la_memoria(con: sqlite3.Connection, p: _Parte, desde: str) -> None:
    from . import piezas
    error_avisos = memoria.leer(con, "avisos_error")
    hechas, fallos, sin_salir = Counter(), {}, 0
    for b in memoria.bitacora(con, 500, desde=desde):
        if b["accion"] == "resumen_del_dia" and b["ok"]:   # el propio parte de ayer; si no salió, sí cuenta
            continue
        if b["ok"]:
            hechas[b["accion"]] += 1
        elif error_avisos and str(b["resultado"]).startswith("no salió:"):
            # Un aviso que no salió (`avisos.intentar`) ya lo cuenta la línea
            # de los avisos: dos líneas para un mismo fallo inflan la cifra.
            sin_salir += 1
        else:
            # Lo más nuevo primero: el primero que se ve de cada una es su último error.
            f = fallos.setdefault(b["accion"], {"n": 0, "resultado": b["resultado"]})
            f["n"] += 1
    if hechas:
        top = hechas.most_common(3)
        resto = sum(hechas.values()) - sum(n for _, n in top)
        p.paso.append(f"· Hice {_s(sum(hechas.values()), 'cosa', 'cosas')}: "
                      + ", ".join(f"{_nombre_accion(a)} ({n})" for a, n in top)
                      + (f" y {resto} más" if resto else ""))
    for accion, f in list(fallos.items())[:TOPE]:
        veces = f" (×{f['n']})" if f["n"] > 1 else ""
        p.fallo(f["n"], f"· {_nombre_accion(accion)}{veces}: {_corto(f['resultado'])}")
    if len(fallos) > TOPE:
        resto = list(fallos.values())[TOPE:]
        p.fallo(sum(f["n"] for f in resto), f"· y {_s(len(resto), 'acción más', 'acciones más')} con error")
    if error_avisos:
        cuantos = f" ({_s(sin_salir, 'aviso perdido', 'avisos perdidos')})" if sin_salir else ""
        p.fallo(max(1, sin_salir), f"· Los avisos al teléfono no salen{cuantos}: {_corto(error_avisos)}")
    # Sólo las fuentes encendidas: una apagada guarda su último error para siempre.
    activas = {k for k, v in piezas.ajustes_fuentes().items() if isinstance(v, dict) and v.get("activa")}
    for fuente, e in memoria.estados_fuentes(con).items():
        if e.get("error") and fuente in activas:
            p.fallo(1, f"· La fuente {fuente} falla: {_corto(e['error'])}")


def _del_orquestador(p: _Parte, desde: str) -> None:
    """Lo que se movió en el orquestador. Lo que pregunta o pide confirmar
    es de «Te espera», y sale de `asuntos`."""
    from .. import orquestador as orq
    movidas = [t for t in orq.listar() if (t.get("creada") or "") >= desde or (t.get("cerrada") or "") >= desde]
    for t in movidas[-3:]:
        p.paso.append(f"· Orquestador, {orq.ETIQUETA.get(t['estado'], t['estado'])}: «{_corto(t['pedido'], 60)}»")
    if len(movidas) > 3:
        p.paso.append(f"· y {_s(len(movidas) - 3, 'tarea más', 'tareas más')} del orquestador")


def _del_hub(leer):
    """Una lectura de `hub.db` con su propia conexión, para que cada una vaya en su try."""
    from .. import db
    h = db.conectar()
    try:
        return leer(h)
    finally:
        h.close()


def _de_los_avisos(p: _Parte, desde: str) -> None:
    """Los avisos del hub que salieron y siguen igual.

    La tabla guarda el último episodio de cada cosa y borra la marca al cambiar,
    así que no sirve para contar «avisos de anoche» (saldrían menos, regla 13).
    Lo que falla es lo que sigue en pie, sea de cuando sea; lo que pasó (una
    sesión que se quedó quieta), sólo lo de las últimas 24 h. La sesión que
    sigue preguntando es de «Te espera», y sale de `asuntos`."""
    from .. import avisos as avisos_hub
    siguen, de_anoche = _del_hub(lambda h: (avisos_hub.ultimos(h, 200), avisos_hub.ultimos(h, 200, desde=desde)))
    quietas = sum(1 for f in de_anoche if f["clave"].startswith("%") and f["estado"] != "preguntando")
    for f in siguen:
        clave, estado = f["clave"], f["estado"]
        if clave.startswith("%"):
            continue
        nombre = {"hub": "el muestreo del hub", "secretario": "el secretario"}.get(clave, clave.removeprefix("maquina:"))
        p.fallo(1, f"· Te avisé y sigue igual: {nombre}, {estado}")
    if quietas:
        p.paso.append(f"· {_s(quietas, 'sesión acabó o se quedó quieta', 'sesiones acabaron o se quedaron quietas')}"
                      " (te avisé)")


def _de_la_salud(p: _Parte) -> None:
    """Sólo lo que está mal: «aviso» es también «no hay tmux, normal al
    encender» o «ningún slot persistente», y eso no es un fallo."""
    from .. import api
    for x in _del_hub(api.salud):
        if x.get("estado") == "mal":
            p.fallo(1, f"· {x.get('nombre')}: {_corto(x.get('detalle'))}")


def _de_las_sesiones(p: _Parte, desde: str) -> None:
    from .. import registry, transcripts
    corte = datetime.fromisoformat(desde)
    leidas = transcripts.listar_sesiones(registry.cargar(), desde=desde, limite=SESIONES)
    vistas = []
    # `desde` mira la fecha del archivo, que se toca sin que nadie trabaje:
    # cuenta sólo la que tuvo un mensaje de verdad desde entonces (regla 19).
    for x in leidas:
        try:
            if x.get("fin") and datetime.fromisoformat(x["fin"].replace("Z", "+00:00")) >= corte:
                vistas.append(x)
        except ValueError:
            continue
    if not vistas:
        return
    vistas.sort(key=lambda x: x["fin"], reverse=True)
    cuantas = _s(len(vistas), "sesión de Claude", "sesiones de Claude")
    if len(leidas) >= SESIONES:
        cuantas = "al menos " + cuantas   # se miraron las SESIONES más recientes y nada más
    p.paso.append(f"· {cuantas}:\n" + "\n".join(
        f"  {x['proyecto_id']} «{_corto(x.get('titulo') or x.get('primera') or 'sin título', 60)}»"
        for x in vistas[:3]) + (f"\n  y {len(vistas) - 3} más" if len(vistas) > 3 else ""))


def _de_las_fichas(p: _Parte, ahora: datetime) -> None:
    """Las fichas que se abrieron o cerraron desde ayer. Sólo si
    `secretario.yml` dice dónde están (`parte_fichas: <carpeta>`): las fichas
    son del flujo con que se desarrolla el hub, y quien lo instala no las
    tiene. Las que esperan algo de él son de «Te espera», y salen de `asuntos`."""
    from .. import fichas
    from . import piezas
    carpeta = piezas.ajuste("parte_fichas")
    if not carpeta:
        return
    carpeta = Path(str(carpeta)).expanduser()
    if not carpeta.is_dir():
        raise FileNotFoundError(f"no existe la carpeta {carpeta}")
    ayer = (ahora - timedelta(days=1)).date().isoformat()
    todas = fichas.listar(carpeta)
    abiertas = sum(1 for f in todas if str(f.get("abierta") or "") >= ayer)
    cerradas = sum(1 for f in todas if str(f.get("cerrada") or "") >= ayer)
    if abiertas or cerradas:
        p.paso.append("· Fichas desde ayer: " + ", ".join(
            x for x in (_s(abiertas, "nueva", "nuevas") if abiertas else "",
                        _s(cerradas, "cerrada", "cerradas") if cerradas else "") if x))
