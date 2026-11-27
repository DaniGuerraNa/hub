"""El bucle de `hub-secretario` (decisión 298).

Dos hilos, cada uno con su conexión, para que una cosa lenta no frene a la otra:

- **conversación**: mira cada segundo si el dueño escribió y contesta. Es lo
  único que alguien está esperando con la pantalla delante.
- **ciclo**: cada `CICLO` segundos manda los recordatorios, mira los
  disparadores, ejecuta lo que el dueño aprobó y, al final, lee las fuentes
  que tocan, pasa el triaje y cierra los hilos quietos. El orden importa: lo
  que tiene hora no va detrás de lo que espera al modelo (C-0267).

**Lo aprobado se hace como mucho una vez** (C-0315): cada solicitud se
reclama justo antes de ejecutarla, y lo que el arranque encuentra a medias se
cierra como «no sé si se hizo» y se le dice; nunca se repite sola.

🔴 **Ninguno muere por una vuelta mala** (regla dura 2): cada paso va en su
propio `try` (regla dura 14), y un fallo se apunta en la bitácora y se sigue.
Un secretario que se cae sin que nadie lo note es peor que no tenerlo: el
recordatorio que no salió es justo el que importaba.

**Parar es una petición que se atiende** (C-0266): con SIGTERM no se empieza
nada más, lo que está a medias —el turno que se contesta, el paso del ciclo—
tiene `ESPERA_AL_PARAR_S` para acabar, y se sale con 0. Antes moría en el acto
y cada reinicio hecho a propósito era un «Failed» en el journal.
"""

from __future__ import annotations

import json
import signal
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from .. import copia_base, reloj
from ..db import transaccion
from . import asuntos
from . import avisos, consultas, conversacion, disparadores, memoria, motor, piezas, recordatorios, sesiones, triaje
from . import investigar
from . import lotes
from . import de_proyectos
from . import delegados
from . import huecos

CICLO = 30
#: Lo que se espera, al parar, a que acabe lo que está a medias (C-0266). Menos
#: que el `TimeoutStopSec` de la plantilla del servicio, que es quien corta de
#: verdad: si systemd se cansa antes, lo mata él y vuelve el «Failed»
#: (`tests/test_secretario_parada.py` los compara).
ESPERA_AL_PARAR_S = 45


def _paso(con: sqlite3.Connection, nombre: str, funcion, *args):
    try:
        return funcion(con, *args)
    except Exception as exc:  # noqa: BLE001 — la regla dura 2 es exactamente esto
        traceback.print_exc()
        try:
            memoria.apuntar(con, nombre, resultado=f"{type(exc).__name__}: {exc}", ok=False)
        except sqlite3.Error:
            pass
        return None


#: Lo que dijo la copia diaria la última vez que falló (C-0417), o None si
#: salió. Para apuntarlo una vez por racha y no en cada vuelta.
_racha_copia: str | None = None


def copia_diaria(con: sqlite3.Connection):
    """La copia de la memoria (regla dura 1, decisión 299), dicha una vez por racha.

    Con la base defectuosa, `copia_base.hacer` vuelve a lanzar en cada vuelta
    (30 s) mientras dure, y `_paso` dejaba una fila y una traza en cada una
    (revisión cruzada: 5 vueltas, 5 filas, 5 trazas). Aquí, como en el ciclo
    lento del snapshotter: la traza y la fila la primera vez y si cambia el
    motivo; mientras siga igual, nada; y una fila al volver a salir. Se
    intenta en cada vuelta igual: el ciclo no se queda sordo (regla dura 2)."""
    global _racha_copia
    try:
        hecha = copia_base.hacer(con, prefijo=copia_base.PREFIJO_SECRETARIO)
    except Exception as exc:  # noqa: BLE001 — la regla dura 2, contada una vez
        motivo = f"{type(exc).__name__}: {exc}"
        if motivo != _racha_copia:
            traceback.print_exc()
            # Si la bitácora no deja, la racha no empieza: se dice en la vuelta siguiente.
            memoria.apuntar(con, "copia", resultado=f"{motivo} (se apunta una vez mientras dure)", ok=False)
            _racha_copia = motivo
        return None
    if _racha_copia is not None:
        print("[secretario] copia: vuelve a salir", flush=True)
        memoria.apuntar(con, "copia", resultado="la copia diaria vuelve a salir")
        _racha_copia = None
    return hecha


def leer_fuentes(con: sqlite3.Connection, forzar: bool = False) -> int:
    """Las fuentes encendidas cuyo intervalo ya pasó. Devuelve cuántos eventos entraron."""
    ajustes = piezas.ajustes_fuentes()
    nuevos: list[int] = []
    for fid, fuente in piezas.fuentes().items():
        a = ajustes.get(fid) or {}
        if not a.get("activa"):
            continue
        est = memoria.estado_fuente(con, fid)
        if est and est["leida"] and not forzar:
            pasado = (datetime.now(timezone.utc) - datetime.fromisoformat(est["leida"])).total_seconds()
            if pasado < fuente.intervalo:
                continue
        falta = fuente.disponible()
        if falta:
            memoria.anotar_fuente(con, fid, est["cursor"] if est else "", error=falta)
            continue
        try:
            eventos, cursor = fuente.leer(est["cursor"] if est else "", a)
        except Exception as exc:  # noqa: BLE001 — una fuente rota no tumba a las demás
            memoria.anotar_fuente(con, fid, est["cursor"] if est else "", error=f"{type(exc).__name__}: {exc}"[:500])
            continue
        entrados = [i for i in (memoria.guardar_evento(con, e) for e in eventos) if i]
        nuevos += entrados
        memoria.anotar_fuente(con, fid, cursor, error=None, sumar=len(entrados))
    if nuevos:
        _paso(con, "disparadores", disparadores.por_eventos, nuevos)
    return len(nuevos)


#: Lo que queda en la solicitud y en la bitácora de una que se cortó a mitad (C-0315).
RESULTADO_CORTADA = "se cortó a mitad: no sé si llegó a hacerse; no se repite sola"
#: Lo ya ejecutado en ESTE proceso que no se pudo cerrar (la base ocupada más
#: de sus diez segundos): `{id: (fila, estado, resultado, ok, params, paso)}`.
#: El servicio no muere por eso, así que el arranque no lo recogería nunca: se
#: cierra en la llamada siguiente, sin repetir la acción. Sólo lo toca el hilo
#: del ciclo. Si el proceso muere con algo dentro, el arranque lo cierra como
#: cortada, que para el proceso nuevo es la verdad.
_sin_cerrar: dict[int, tuple] = {}


def _cerrar(con: sqlite3.Connection, s: sqlite3.Row, estado: str, resultado: str, ok: bool, params: dict,
            desde: int = 0) -> None:
    """Deja dicho cómo acabó una solicitud ya ejecutada: su estado (por id,
    esté como esté: quien la hizo sabe la verdad), la bitácora y su hilo.
    Si la base no deja, lo guarda en `_sin_cerrar` con el paso por el que
    iba —para no apuntarlo ni decirlo dos veces— y relanza."""
    # Tapados después de hacerla: un dato recién propuesto ya está en la ficha
    # y queda con su nombre. La solicitud cerrada no los necesita en claro, y
    # la bitácora no es otra ficha (382), tampoco con lo que no llegó a
    # guardarse en ella (C-0431).
    tapados = piezas.params_tapados(s["accion"], params)
    pasos = (
        lambda: memoria.resolver_solicitud(con, s["id"], estado, resultado, params=tapados),
        lambda: memoria.apuntar(con, s["accion"], nivel="aprobada", params=tapados,
                                motivo=s["motivo"], resultado=resultado, ok=ok),
        lambda: s["hilo"] and conversacion.decir(con, s["hilo"], ("Hecho: " if ok else "No salió: ") + resultado),
    )
    for i in range(desde, len(pasos)):
        try:
            pasos[i]()
        except sqlite3.Error:
            _sin_cerrar[s["id"]] = (s, estado, resultado, ok, params, i)
            raise
    _sin_cerrar.pop(s["id"], None)


def ejecutar_aprobadas(con: sqlite3.Connection) -> int:
    """Lo que el dueño aprobó en la pantalla: lo hace este servicio, que es quien
    tiene las llaves (decisión 298); `hub-web` sólo marcó «aprobada».

    🔴 Cada una se **reclama** justo antes de ejecutarla (`aprobada` →
    `ejecutando`, C-0315) y sólo la ejecuta quien cambió la fila. Una a una,
    nunca el lote: si algo corta en la primera, las demás siguen «aprobada» y
    se hacen después sin duda ninguna. La que quede `ejecutando` no vuelve a
    entrar aquí: la cierra el arranque (`recoger_cortadas`), sin repetirla."""
    n, sin_cerrar = 0, None
    # Lo que este proceso ya hizo y no pudo cerrar: primero, y sin ejecutar nada.
    # Si sigue sin dejarse, se dice al final: una que no se cierra nunca no
    # puede dejar sin hacer lo que apruebe después (regla dura 2).
    for pendiente in list(_sin_cerrar.values()):
        try:
            _cerrar(con, *pendiente)
            n += 1
        except sqlite3.Error as exc:
            sin_cerrar = sin_cerrar or exc
    acciones = piezas.acciones()
    for s in con.execute("SELECT * FROM solicitud WHERE estado = 'aprobada' ORDER BY id").fetchall():
        a = acciones.get(s["accion"])
        params = json.loads(s["params"] or "{}")
        estado = None
        # Hasta aquí `resuelta` es la hora en que la aprobó; reclamarla y
        # cerrarla la pisan (C-0271): se mide con la fila leída antes.
        espero = (reloj.instante() - reloj.instante(s["resuelta"])).total_seconds() if s["resuelta"] else None
        # Si la base está ocupada lanza aquí, antes de hacer nada: sigue
        # «aprobada» y la reintenta la vuelta. None: la tomó otro proceso
        # (una vuelta lanzada a mano con el servicio vivo).
        if memoria.resolver_solicitud(con, s["id"], "ejecutando", de="aprobada") is None:
            continue
        t0 = time.monotonic()
        if not a:
            resultado, ok = "esa acción ya no existe", False
        elif a.caduca_s and (reloj.instante() - reloj.instante(s["creada"])).total_seconds() > a.caduca_s:
            resultado, ok, estado = (f"no lo hice: pasaron más de {a.caduca_s // 60} min desde que te lo pedí, y la "
                                     "PC ya puede estar distinta. Si aún lo quieres, pídemelo otra vez"), False, "caducada"
        else:
            try:
                # Sólo aquí se sabe que el dueño la aprobó: no viaja en
                # `params`, que en `auto` los escribe el modelo (C-0151).
                if getattr(a, "quiere_aprobacion", False):
                    # Y en qué hilo se pidió, a la que deja el informe después (C-0507).
                    extra = {"hilo": s["hilo"]} if getattr(a, "quiere_hilo", False) else {}
                    resultado, ok = a.ejecutar(con, params, aprobada=True, **extra), True
                else:
                    resultado, ok = a.ejecutar(con, params), True
            except Exception as exc:  # noqa: BLE001
                resultado, ok = f"falló: {exc}", False
        _cerrar(con, s, estado or ("hecha" if ok else "fallo"), str(resultado), ok, params)
        if espero is not None:
            # Una línea en el journal para poder medir de «Aprobar» a hecho, que
            # en la base no queda (C-0271). Sólo qué acción y cuánto: ni sus
            # parámetros ni su resultado (regla dura 22).
            print(f"[aprobada] {s['accion']}: esperó {espero:.0f} s desde que se aprobó y tardó "
                  f"{time.monotonic() - t0:.1f} s", flush=True)
        n += 1
    if sin_cerrar is not None:
        raise sin_cerrar       # en voz alta: `_paso` lo apunta (regla 21)
    return n


#: Las solicitudes que estaban `ejecutando` cuando arrancó ESTE servicio y
#: aún no se han cerrado como cortadas (C-0315). Es lo que distingue «cayó»
#: de «sigue en ello» sin apuntar en la base quién la tiene: sólo lo llena
#: `recoger_cortadas`, desde `correr`. En cualquier otro proceso (una vuelta
#: lanzada a mano) está vacío, y ahí nunca se cierra nada como cortada.
_cortadas: set[int] = set()


def recoger_cortadas(con: sqlite3.Connection) -> int:
    """Lo que el servicio encuentra `ejecutando` al arrancar: estaba a medias
    cuando murió el anterior. Lo apunta en `_cortadas` y lo cierra
    (`cerrar_cortadas`); lo que no se deje cerrar ahora lo reintenta cada vuelta.

    🔴 **Sólo desde `correr`, antes de sus hilos y de la primera vuelta.** Al
    arrancar no hay otro servicio vivo (como en `conversacion.retomar_cortados`);
    mirado más tarde, lo `ejecutando` puede ser lo que se está haciendo ahora."""
    _cortadas.update(f["id"] for f in con.execute("SELECT id FROM solicitud WHERE estado = 'ejecutando'"))
    return cerrar_cortadas(con)


def cerrar_cortadas(con: sqlite3.Connection) -> int:
    """Cierra como `cortada` lo que `recoger_cortadas` vio a medias: se apunta
    como fallo y se le dice en su chat —también sin hilo: es una duda que sólo
    él puede resolver—. Devuelve cuántas cerró. No mira la tabla: sólo lo ya
    visto al arrancar, así que desde una vuelta es seguro reintentarlo.

    🔴 **Nunca ejecuta nada**: tras un corte no se sabe si la acción llegó a
    hacerse, y repetir una irreversible es peor que preguntar (lo decidió el
    dueño; tampoco lo que podría repetirse sin daño).

    El estado, la bitácora y el chat van en una transacción: si no se le pudo
    decir, no queda `cortada` a medias y callada; sigue `ejecutando` —que aquí
    ya no se ejecuta— y se reintenta en la vuelta siguiente.

    No sale por `avisos` ni entra en «Te espera»: son listas cerradas (regla
    dura 3, decisión 379). Sin sus parámetros: pueden llevar sus datos (382)."""
    acciones = piezas.acciones()
    n, fallo = 0, None
    for sid in sorted(_cortadas):
        # Cada una en su `try`: una que no se deja cerrar no frena a las demás.
        try:
            with transaccion(con):
                # Leídos y tapados dentro de la misma transacción que la cierra
                # (C-0431): cortada es final y no se repite, así que en claro
                # ya no sirven.
                tapados = piezas.solicitud_tapada(con, sid)
                fila = memoria.resolver_solicitud(con, sid, "cortada", RESULTADO_CORTADA, de="ejecutando",
                                                  params=tapados)
                if fila is not None:
                    memoria.apuntar(con, fila["accion"], nivel="aprobada", params=tapados,
                                    motivo=fila["motivo"], resultado=RESULTADO_CORTADA, ok=False)
                    a = acciones.get(fila["accion"])
                    nombre = a.nombre if a and a.nombre else fila["accion"].replace("_", " ")
                    motivo = f" ({fila['motivo']})" if fila["motivo"] else ""
                    conversacion.decir(con, fila["hilo"],
                                       f"Me reinicié a mitad de «{nombre}»{motivo}, que habías aprobado, y no sé si "
                                       "llegó a hacerse. No la repito sola: míralo y, si no se hizo, pídemela otra vez.")
            # Cerrada, o ya no estaba a medias (la cerró quien la hacía): fuera de la lista.
            _cortadas.discard(sid)
            n += fila is not None
        except Exception as exc:  # noqa: BLE001 — se dice abajo, cuando ya se intentaron todas
            fallo = fallo or exc
    if fallo is not None:
        raise fallo        # en voz alta: `_paso` lo apunta (regla 21)
    return n


#: Cada cuánto se mira, entre vuelta y vuelta, si aprobó algo (C-0271).
MIRAR_APROBADAS_S = 1.0
APROBADA = "SELECT 1 FROM solicitud WHERE estado = 'aprobada' LIMIT 1"


def _entre_vueltas(con: sqlite3.Connection, parar: threading.Event, segundos: float) -> None:
    """La espera hasta la vuelta siguiente, atenta a lo que el dueño apruebe.

    Aprobar es él con la pantalla delante —y con `escribir_en_sesion`, su
    mensaje a la sesión es lo que espera—: no aguarda los hasta 30 s que
    falten para la vuelta (C-0271). Se hace aquí, en el hilo del ciclo, y no
    en el de la conversación: una acción lenta no puede dejar el chat sin
    contestar, y con un solo hilo que las ejecute ninguna se hace dos veces.
    Si el ciclo está en un paso largo, espera a que acabe ese paso."""
    fin = time.monotonic() + segundos
    while not parar.is_set():
        queda = fin - time.monotonic()
        if queda <= 0:
            return
        try:
            hay = con.execute(APROBADA).fetchone()
        except sqlite3.Error:
            hay = None   # la base ocupada: lo hará la vuelta, que sí lo apunta si falla
        if hay:
            if _paso(con, "aprobadas", ejecutar_aprobadas) is None:
                # Falló a medias (la base ocupada, sobre todo): o no llegó a
                # reclamarla y sigue «aprobada» sin hacer, o la hizo y no pudo
                # cerrarla (`_sin_cerrar`, C-0315). Repetirse ya no puede, pero
                # insistir cada segundo contra una base ocupada no la
                # desocupa: lo que falte lo hace la vuelta, como siempre.
                parar.wait(max(0.0, fin - time.monotonic()))
                return
            # Aprobar cambia lo que espera de él: la cuenta del globo, al día.
            _paso(con, "asuntos", asuntos.recalcular)
        parar.wait(min(MIRAR_APROBADAS_S, queda))


def una_vuelta(con: sqlite3.Connection, parar: threading.Event | None = None) -> None:
    def paso(nombre: str, funcion, *args) -> None:
        # Con la parada pedida no se empieza nada más (C-0266): lo que falte
        # lo hace la primera vuelta tras arrancar, y no se corta a medias.
        if parar is None or not parar.is_set():
            _paso(con, nombre, funcion, *args)

    memoria.poner(con, "latido", memoria.ahora())
    # 🔴 Lo que tiene hora, lo primero, y sin nada delante que espere a la red
    # o al modelo (C-0267): un recordatorio es «con su hora» (302) y lo
    # grabado se corta al poco de colgar (378). Iban detrás del triaje, que
    # medido del 1 al 11-nov llegó a 136 s (77 de 986 llamadas, más de 30 s).
    paso("recordatorios", recordatorios.revisar)
    paso("parar grabación", disparadores.parar_si_acabo)
    # Lo que quedó a medias al arrancar y no se pudo cerrar entonces (la base
    # ocupada): hasta que salga. Sin nada pendiente, ni se mira (C-0315).
    if _cortadas:
        paso("cortadas", cerrar_cortadas)
    # Lo que aprobó, antes que nada que pregunte al modelo (C-0271): iba
    # detrás del triaje y de los disparadores, y él lo espera con el teléfono
    # en la mano. Entre vuelta y vuelta lo recoge `_entre_vueltas`.
    paso("aprobadas", ejecutar_aprobadas)
    # Éstos también tienen hora, pero pueden preguntarle al modelo (`pide`) o
    # a la agenda: detrás de los dos de arriba, que no esperan a nadie.
    paso("horario", disparadores.por_horario)
    paso("estado", disparadores.por_estado)
    paso("agenda", disparadores.por_agenda)
    paso("consultas", consultas.atender)
    # Lo que dejaron sus proyectos en su cola (387): antes de la cuenta, para
    # que una pregunta suya salga en el globo en esta misma vuelta.
    paso("de proyectos", de_proyectos.recoger)
    # Lo que delegó y ya se cerró vuelve a su chat, con lo que se vio (384).
    paso("delegados", delegados.recoger)
    # Lo que no supo hacer y ya sabe, una vez y en el chat (C-0252): nunca al
    # teléfono, que no es un aviso (regla dura 3).
    paso("huecos", huecos.recoger)
    # Después de lo que cambia lo que espera de él (lo aprobado, lo que el
    # orquestador le elevó): la cuenta del globo sale ya al día (379, 380).
    paso("asuntos", asuntos.recalcular)
    # Al final, lo que no tiene hora y espera sin tope corto: las fuentes a la
    # red (Telethon reintenta sin ella) y el triaje y el resumen de cada hilo
    # al modelo. Lo que dejen —un compromiso, un asunto— lo recoge la vuelta
    # siguiente, que empieza por los recordatorios (C-0267).
    paso("fuentes", leer_fuentes)
    paso("triaje", triaje.triar, conversacion._dueno())
    paso("cerrar_hilos", conversacion.cerrar_inactivos)
    # Lo que sólo vive aquí se copia una vez al día, como `hub.db` (regla dura 1).
    # Una vez por racha si falla (C-0417), no en cada vuelta.
    paso("copia", copia_diaria)


def aviso_de_prueba(con: sqlite3.Connection) -> str | None:
    """El «Mandar uno de prueba» de la pantalla: lo deja `hub-web` y lo manda
    este servicio, el único con la clave (decisión 311). Devuelve el canal."""
    if not memoria.leer(con, "aviso_prueba"):
        return None
    memoria.poner(con, "aviso_prueba", None)
    try:
        canal = avisos.mandar("Si lees esto, los avisos del secretario te llegan aquí.", titulo="Aviso de prueba")
    except (avisos.SinCanal, LookupError) as exc:
        memoria.apuntar(con, "aviso de prueba", resultado=f"no salió: {exc}", ok=False)
        return None
    memoria.apuntar(con, "aviso de prueba", nivel="auto", resultado=f"enviado por {canal}")
    return canal


RECOGER_S = 0.2
PENDIENTE = "SELECT 1 FROM turno WHERE estado = 'pendiente' AND rol = 'dueno' LIMIT 1"


#: Lo que se espera tras un fallo del hilo de la conversación antes de volver
#: a mirar (C-0268): una base bloqueada no se desbloquea antes por insistir
#: cinco veces por segundo, y cada intento deja su línea en el journal.
TRAS_FALLO_S = 5


def _bucle_conversacion(parar: threading.Event) -> None:
    con: sqlite3.Connection | None = None
    siguiente = 0.0
    fallos = 0
    while not parar.is_set():
        # 🔴 Todo el cuerpo en su `try` (regla dura 2, decisión 376): abrir la
        # base y mirar si hay turnos iban fuera, y una base bloqueada más de
        # sus diez segundos terminaba este hilo mientras el otro seguía
        # latiendo. La pantalla decía «en marcha» y nadie contestaba (C-0268).
        try:
            if con is None:
                con = memoria.conectar()
            if time.monotonic() >= siguiente:
                siguiente = time.monotonic() + 1
                # El latido también aquí: el ciclo lento puede pasar un minuto en el
                # triaje, y la pantalla diría «no está en marcha» mientras contesta.
                _paso(con, "latido", lambda c: memoria.poner(c, "latido", memoria.ahora()))
                _paso(con, "motor abierto", lambda c: motor.podar())
                _paso(con, "aviso de prueba", aviso_de_prueba)
            # Lo que el dueño acaba de decir se recoge a los 0,2 s, no al segundo
            # (C-0155); mirar si hay algo es una consulta por índice, y el latido
            # y lo demás siguen a su ritmo para no escribir cinco veces por segundo.
            if con.execute(PENDIENTE).fetchone():
                # Con la parada pedida, el turno que se contesta acaba y el
                # siguiente espera al arranque (C-0266).
                _paso(con, "conversacion", conversacion.atender, parar.is_set)
            fallos = 0
        except Exception as exc:  # noqa: BLE001 — la regla dura 2 es exactamente esto
            fallos += 1
            # En voz alta (regla 21): entero la primera vez, y luego una línea
            # por intento, que un fallo que dura no llene el journal de trazas.
            if fallos == 1:
                traceback.print_exc()
            else:
                print(f"hub-secretario: la conversación sigue sin poder mirar si le escribieron "
                      f"({type(exc).__name__}: {exc}); intento {fallos}", file=sys.stderr, flush=True)
            # Conexión nueva al volver: una que dio un error de disco puede no
            # servir más, y abrirla cuesta poco.
            if con is not None:
                try:
                    con.close()
                except sqlite3.Error:
                    pass
                con = None
            parar.wait(TRAS_FALLO_S)
            continue
        parar.wait(RECOGER_S)


#: Cuántas vueltas se intenta devolver a la cola lo que se cortó al reiniciar
#: (C-0308) si el intento falla (la base ocupada al arrancar, sobre todo). Con
#: tope: uno que falla siempre no llena la bitácora cada 15 s.
RETOMAR_INTENTOS = 3


def _bucle_resumenes(parar: threading.Event) -> None:
    """Lo que se hace aparte, en su hilo: los resúmenes de sesiones largas
    (C-0163), las investigaciones en la web (385) y las listas de comandos
    preparados que él aprobó (`lotes`, C-0507). Una llamada puede tardar
    minutos, y en el ciclo lento retrasaría recordatorios y avisos. Cada uno
    en su paso: uno que falla siempre no deja al otro sin atender (regla 2).

    Lo primero, lo que se cortó al reiniciar vuelve a su cola (C-0308). Va
    aquí y no en `correr` porque este hilo es el único que saca de esas colas:
    lo que encuentre marcado «en curso» antes de atender no lo hace nadie."""
    con: sqlite3.Connection | None = None
    fallos = 0
    por_retomar = {"retomar resúmenes": sesiones.retomar, "retomar investigaciones": investigar.retomar,
                   "retomar listas de comandos": lotes.retomar}
    intentos = 0
    while not parar.is_set():
        # 🔴 Abrir la base, en su `try` (regla dura 2, C-0314): fuera de él, un
        # fallo terminaba este hilo y el servicio seguía latiendo sin resumir
        # ni investigar nunca. Como en `_bucle_conversacion` (C-0268).
        if con is None:
            try:
                con = memoria.conectar()
                fallos = 0
            except Exception as exc:  # noqa: BLE001 — la regla dura 2 es exactamente esto
                fallos += 1
                # En voz alta (regla 21): entero la primera vez, luego una línea por intento.
                if fallos == 1:
                    traceback.print_exc()
                else:
                    print(f"hub-secretario: los resúmenes y las investigaciones siguen sin poder abrir la base "
                          f"({type(exc).__name__}: {exc}); intento {fallos}", file=sys.stderr, flush=True)
                parar.wait(TRAS_FALLO_S)
                continue
        if por_retomar and intentos < RETOMAR_INTENTOS:
            intentos += 1
            # Cada uno en su paso; el que falla (None) se intenta en la vuelta
            # siguiente, y no impide atender: lo peor es lo de antes, perderlo.
            por_retomar = {n: f for n, f in por_retomar.items() if _paso(con, n, f) is None}
        _paso(con, "resumenes", sesiones.atender)
        # Con la parada pedida no se saca otra (C-0308): moriría al instante,
        # y sería un corte más de los `MAX_REINTENTOS` que tiene.
        if parar.is_set():
            break
        _paso(con, "investigaciones", investigar.atender)
        if parar.is_set():
            break
        # Una lista de comandos que él aprobó (C-0507): en su paso, como las demás.
        _paso(con, "listas de comandos", lotes.atender)
        parar.wait(15)


class _SeAcaboLaEspera(BaseException):
    """Pasó `ESPERA_AL_PARAR_S` desde que se pidió parar y algo sigue en marcha.

    `BaseException` a propósito: tiene que atravesar los `except Exception` de
    cada paso —que existen para que una vuelta mala no tumbe el servicio— y
    cortar el que esté esperando al modelo."""


def atender_parada(parar: threading.Event) -> None:
    """SIGTERM deja de matar en el acto: pide parar y pone el tope de la espera.

    Sólo levanta `parar`; quien espera y sale es `correr`. El tope va por
    SIGALRM y no por un hilo porque lo que hay que cortar es el hilo principal
    (el ciclo va en él), y sólo ahí entrega Python las señales."""
    def pedir(*_) -> None:
        if not parar.is_set():
            # El tope, antes que nada (C-0314): `parar.set()` toma el cerrojo
            # interno del `Event`, y si la señal cae mientras el hilo principal
            # lo tiene (en `parar.wait`), este manejador se bloquea a sí mismo.
            # Con el tope ya armado, SIGALRM lo saca de ahí y se sale igual.
            signal.setitimer(signal.ITIMER_REAL, ESPERA_AL_PARAR_S)
            parar.set()

    def tope(*_) -> None:
        raise _SeAcaboLaEspera

    signal.signal(signal.SIGALRM, tope)
    signal.signal(signal.SIGTERM, pedir)


def correr() -> None:  # pragma: no cover - lo prueba tests/test_secretario_parada.py, en otro proceso
    con = memoria.conectar()
    conversacion.retomar_cortados(con)
    # 🔴 Aquí y sólo aquí, antes de los hilos y de la primera vuelta (C-0315):
    # lo que quedó «ejecutando» es de un servicio que ya no está. En su paso:
    # si falla, se apunta y el servicio arranca igual (regla dura 2); lo que
    # falte por cerrar lo reintenta cada vuelta.
    _paso(con, "cortadas", recoger_cortadas)
    # Las claves de Web Push, si no existen: sin la pública la pantalla no
    # puede ofrecer «Activar avisos».
    try:
        from .avisos import webpush
        webpush.preparar()
    except Exception:  # noqa: BLE001 — sin avisos propios el resto sigue
        traceback.print_exc()
    parar = threading.Event()
    atender_parada(parar)
    charla = threading.Thread(target=_bucle_conversacion, args=(parar,), daemon=True, name="conversacion")
    charla.start()
    threading.Thread(target=_bucle_resumenes, args=(parar,), daemon=True, name="resumenes").start()
    print("hub-secretario en marcha", flush=True)
    try:
        while not parar.is_set():
            t0 = time.monotonic()
            try:
                una_vuelta(con, parar)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            _entre_vueltas(con, parar, max(1.0, CICLO - (time.monotonic() - t0)))
        # Pidieron parar. El turno que se esté contestando se deja acabar: es
        # lo único que alguien espera con la pantalla delante. Lo aparte
        # (resúmenes, investigaciones) tarda minutos y no se espera: se corta,
        # y al arrancar vuelve a su cola y se le dice (`_bucle_resumenes`, C-0308).
        charla.join()
        # Los `claude` abiertos se cierran como siempre, por su entrada, y no
        # con el SIGKILL que systemd les manda al irse el proceso principal.
        motor.soltar()
        signal.setitimer(signal.ITIMER_REAL, 0)
    except _SeAcaboLaEspera:
        # Los hilos son `daemon`: no impiden salir. El turno que quede
        # «atendiendo» lo recoge `retomar_cortados` al arrancar.
        print(f"hub-secretario: algo seguía a medias a los {ESPERA_AL_PARAR_S:g} s de pedirle parar; "
              "se retoma al arrancar", flush=True)
    print("hub-secretario parado", flush=True)
