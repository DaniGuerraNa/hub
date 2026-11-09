"""El bucle de `hub-secretario` (decisión 298).

Dos hilos, cada uno con su conexión, para que una cosa lenta no frene a la otra:

- **conversación**: mira cada segundo si el dueño escribió y contesta. Es lo
  único que alguien está esperando con la pantalla delante.
- **ciclo**: cada `CICLO` segundos lee las fuentes que tocan, pasa el triaje,
  manda los recordatorios, mira los disparadores, ejecuta lo que el dueño
  aprobó y cierra los hilos quietos.

🔴 **Ninguno muere por una vuelta mala** (regla dura 2): cada paso va en su
propio `try` (regla dura 14), y un fallo se apunta en la bitácora y se sigue.
Un secretario que se cae sin que nadie lo note es peor que no tenerlo: el
recordatorio que no salió es justo el que importaba.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import traceback
from datetime import datetime, timezone

from .. import copia_base
from . import asuntos
from . import avisos, consultas, conversacion, disparadores, memoria, motor, piezas, recordatorios, sesiones, triaje
from . import investigar
from . import de_proyectos
from . import delegados
from . import misdatos

CICLO = 30


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


def ejecutar_aprobadas(con: sqlite3.Connection) -> int:
    """Lo que el dueño aprobó en la pantalla: lo hace este servicio, que es quien
    tiene las llaves (decisión 298); `hub-web` sólo marcó «aprobada»."""
    n = 0
    acciones = piezas.acciones()
    for s in con.execute("SELECT * FROM solicitud WHERE estado = 'aprobada' ORDER BY id").fetchall():
        a = acciones.get(s["accion"])
        params = json.loads(s["params"] or "{}")
        if not a:
            resultado, ok = "esa acción ya no existe", False
        else:
            try:
                # Sólo aquí se sabe que el dueño la aprobó: no viaja en
                # `params`, que en `auto` los escribe el modelo (C-0151).
                if getattr(a, "quiere_aprobacion", False):
                    resultado, ok = a.ejecutar(con, params, aprobada=True), True
                else:
                    resultado, ok = a.ejecutar(con, params), True
            except Exception as exc:  # noqa: BLE001
                resultado, ok = f"falló: {exc}", False
        memoria.resolver_solicitud(con, s["id"], "hecha" if ok else "fallo", str(resultado))
        # Tapada, como en `herramientas.usar_accion`: la bitácora no es otra ficha (382).
        memoria.apuntar(con, s["accion"], nivel="aprobada", params=misdatos.tapar(params), motivo=s["motivo"],
                        resultado=str(resultado), ok=ok)
        if s["hilo"]:
            conversacion.decir(con, s["hilo"], ("Hecho: " if ok else "No salió: ") + str(resultado))
        n += 1
    return n


def una_vuelta(con: sqlite3.Connection) -> None:
    memoria.poner(con, "latido", memoria.ahora())
    _paso(con, "fuentes", leer_fuentes)
    _paso(con, "triaje", triaje.triar, conversacion._dueno())
    _paso(con, "recordatorios", recordatorios.revisar)
    _paso(con, "horario", disparadores.por_horario)
    _paso(con, "estado", disparadores.por_estado)
    _paso(con, "parar grabación", disparadores.parar_si_acabo)
    _paso(con, "agenda", disparadores.por_agenda)
    _paso(con, "aprobadas", ejecutar_aprobadas)
    _paso(con, "consultas", consultas.atender)
    # Lo que dejaron sus proyectos en su cola (387): antes de la cuenta, para
    # que una pregunta suya salga en el globo en esta misma vuelta.
    _paso(con, "de proyectos", de_proyectos.recoger)
    # Lo que delegó y ya se cerró vuelve a su chat, con lo que se vio (384).
    _paso(con, "delegados", delegados.recoger)
    # Después de lo que cambia lo que espera de él (lo aprobado, lo que el
    # orquestador le elevó): la cuenta del globo sale ya al día (379, 380).
    _paso(con, "asuntos", asuntos.recalcular)
    _paso(con, "cerrar_hilos", conversacion.cerrar_inactivos)
    # Lo que sólo vive aquí se copia una vez al día, como `hub.db` (regla dura 1).
    _paso(con, "copia", lambda c: copia_base.hacer(c, prefijo="secretario-"))


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


def _bucle_conversacion(parar: threading.Event) -> None:
    con = memoria.conectar()
    siguiente = 0.0
    while not parar.is_set():
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
            _paso(con, "conversacion", conversacion.atender)
        parar.wait(RECOGER_S)


def _bucle_resumenes(parar: threading.Event) -> None:
    """Lo que se hace aparte, en su hilo: los resúmenes de sesiones largas
    (C-0163) y las investigaciones en la web (385). Una llamada puede tardar
    minutos, y en el ciclo lento retrasaría recordatorios y avisos. Cada uno
    en su paso: uno que falla siempre no deja al otro sin atender (regla 2)."""
    con = memoria.conectar()
    while not parar.is_set():
        _paso(con, "resumenes", sesiones.atender)
        _paso(con, "investigaciones", investigar.atender)
        parar.wait(15)


def correr() -> None:  # pragma: no cover - es el bucle del servicio
    con = memoria.conectar()
    conversacion.retomar_cortados(con)
    # Las claves de Web Push, si no existen: sin la pública la pantalla no
    # puede ofrecer «Activar avisos».
    try:
        from .avisos import webpush
        webpush.preparar()
    except Exception:  # noqa: BLE001 — sin avisos propios el resto sigue
        traceback.print_exc()
    parar = threading.Event()
    threading.Thread(target=_bucle_conversacion, args=(parar,), daemon=True, name="conversacion").start()
    threading.Thread(target=_bucle_resumenes, args=(parar,), daemon=True, name="resumenes").start()
    print("hub-secretario en marcha", flush=True)
    while True:
        t0 = time.monotonic()
        try:
            una_vuelta(con)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(max(1.0, CICLO - (time.monotonic() - t0)))
