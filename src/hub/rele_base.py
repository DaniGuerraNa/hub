"""Lo común a los relés: recorrer lo que llega sin repetir ni perder (decisión 345, C-0130).

Los dos relés (`rele.py`, `rele_encargos.py`) tenían el mismo `for` y los
mismos dos defectos. El offset era una variable local de `una_vuelta`: si un
mensaje lanzaba a mitad, `correr` se quedaba con el viejo y Telegram volvía a
entregar todo lo ya guardado (aparcado dos veces). Y en el chat web pasaba lo
contrario: el cursor avanzaba al bajar el lote, y lo que iba detrás del fallo
se daba por leído sin tratarlo.

Aquí el offset —o el cursor del chat web— avanza mensaje a mensaje, en
cuanto cada uno se ha tratado. Lo que sólo toca la red (cerrar un botón,
contestar un ensayo) va después, en su `try`, y no frena nada: un Telegram
caído no puede hacer que un mensaje ya guardado se trate otra vez.

🔴 **Cada mensaje va en una transacción, y lo que un rollback no deshace va
fuera** (C-0152, decisión 352). Tratar un mensaje puede pegar una respuesta en
un panel o abrir y matar agentes en tmux; con eso dentro de la transacción, el
reintento lo hacía dos veces (revisor de C-0130). Ahora `procesar_mensaje` lo
apunta con `efecto` y corre en `despues` (`ejecutar`), con el offset ya
avanzado: un fallo ahí no repite el mensaje, y su resultado final decide si se
retiran los botones.

Un mensaje que falla siempre atascaría el canal: tras `INTENTOS` se salta y
se apunta el tipo de error, sin el texto (regla dura 22). La base bloqueada no
cuenta como intento: es de la máquina, no del mensaje.

Y el bucle del servicio (`correr`) también es uno para los dos (C-0134): eran
dos copias con las mismas pausas y las mismas excepciones, y el arreglo de una
(C-0138) había que acordarse de hacerlo en la otra.
"""

from __future__ import annotations

import contextlib
import contextvars
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

INTENTOS = 3

# Entre vueltas. El long polling ya espera dentro de `getUpdates`, así que esto
# sólo evita un bucle cerrado cuando la API contesta al instante o falla.
PAUSA = 2

# Tras un fallo. No es reintento inmediato: si Telegram no está, insistir cada
# dos segundos no lo trae antes y llena el registro de ruido.
PAUSA_TRAS_FALLO = 30


def _clave(update: dict) -> tuple[str, int]:
    canal = update.get("canal") or "telegram"
    return canal, int(update.get("id_canal", update.get("update_id", 0)))


def _ocupada(exc: sqlite3.OperationalError) -> bool:
    """Base bloqueada u ocupada: es de la máquina, no del mensaje. Un `no such
    column` también es OperationalError, y ése sí cuenta (revisor de C-0130)."""
    texto = str(exc).lower()
    return "locked" in texto or "busy" in texto


# ── Lo que un rollback no deshace (C-0152) ───────────────────────────────────
#
# Tratar un mensaje va en una transacción; pegar en un panel o abrir y matar
# agentes, no: se apuntan aquí como «efectos» y corren en `despues`, con el
# offset ya avanzado, donde un fallo no repite el mensaje. Sin `diferidos()`
# activo —quien llama desde fuera del relé— se hacen en el acto, como antes.

_diferidos: contextvars.ContextVar[list | None] = contextvars.ContextVar("efectos_del_mensaje", default=None)


@contextlib.contextmanager
def diferidos() -> Iterator[list[Callable[[], Any]]]:
    efectos: list[Callable[[], Any]] = []
    marca = _diferidos.set(efectos)
    try:
        yield efectos
    finally:
        _diferidos.reset(marca)


def efecto(hacer: Callable[[], Any]) -> Any:
    """`hacer()` ahora, o después si se está tratando un mensaje. Devuelve su
    resultado, o None si queda para después."""
    pendientes = _diferidos.get()
    if pendientes is None:
        return hacer()
    pendientes.append(hacer)
    return None


def ejecutar(efectos: list[Callable[[], Any]]) -> Any:
    """Corre los efectos en orden. Devuelve el último resultado que no sea
    None: el final de lo que el mensaje provisionalmente dio por hecho."""
    final = None
    for hacer in efectos:
        if (r := hacer()) is not None:
            final = r
    return final


def recorrer(con: sqlite3.Connection, updates: list[dict], offset: int | None,
             tratar: Callable[[dict], Any], *, registrar: Callable[[str], None],
             fallos: dict, despues: Callable[[dict, Any], None] | None = None,
             confirmar: Callable[[dict], None] | None = None, intentos: int = INTENTOS) -> int | None:
    """Trata cada update y devuelve el offset de Telegram hasta donde se guardó.

    - `tratar(update)` hace lo del mensaje; su resultado pasa a
      `despues(update, resultado)`, para lo que no debe hacer que se repita:
      la red y los efectos de tmux del mensaje (`ejecutar`, 352).
    - Un update marcado con `canal` (el chat web, decisión 246) no mueve el
      offset de Telegram: se confirma con `confirmar(update)` tras guardarlo.
    - `fallos` lo guarda quien llama entre vuelta y vuelta: cuántas veces ha
      fallado cada update.
    - Si `tratar` falla, se apunta y se para ahí: él vuelve en la vuelta
      siguiente, y lo que venía detrás también, en orden.
    """
    def apuntar(texto: str) -> None:
        # Regla dura 2: que falle el propio registro no para la vuelta.
        try:
            registrar(texto)
        except Exception:  # noqa: BLE001
            pass

    for update in updates:
        clave = _clave(update)
        try:
            resultado = tratar(update)
        except Exception as exc:  # noqa: BLE001 - un mensaje malo no tumba el relé
            ocupada = isinstance(exc, sqlite3.OperationalError) and _ocupada(exc)
            n = fallos.get(clave, 0)
            if not ocupada:
                n = fallos[clave] = n + 1
            if ocupada or n < intentos:
                apuntar(f"update {clave[1]} ({clave[0]}) sin tratar ({n}/{intentos}): {type(exc).__name__}")
                return offset
            apuntar(f"update {clave[1]} ({clave[0]}) saltado tras {intentos} intentos: {type(exc).__name__}")
            resultado = None
        fallos.pop(clave, None)
        if update.get("canal"):
            if confirmar:
                confirmar(update)
        else:
            offset = int(update.get("update_id", 0)) + 1
        if despues is not None and resultado is not None:
            try:
                despues(update, resultado)
            except Exception as exc:  # noqa: BLE001 - la red, después y sin frenar
                apuntar(f"update {clave[1]} ({clave[0]}) guardado, pero lo de después falló: {type(exc).__name__}")
    return offset


# ── El bucle del servicio (C-0134) ───────────────────────────────────────────


def _apuntar_fallo(nombre: str, registrar: Callable[[str], None], texto: str) -> None:
    """Apunta lo que tumbó una vuelta. Si ni eso se puede —la base bloqueada—,
    se dice por stderr (lo recoge el journal) y se sigue: el apunte no puede
    sacar del bucle al proceso que existe para no caerse, ni hacerle perder
    el offset al reiniciarlo systemd (regla dura 2, C-0138)."""
    try:
        registrar(texto)
    except Exception as exc:  # noqa: BLE001 - el bucle no puede morir
        print(f"[rele {nombre}] {texto} — y no se pudo apuntar: {exc!r}", file=sys.stderr, flush=True)


def pasos(nombre: str, lista: list[tuple[str, Callable[[], Any]]], *,
          registrar: Callable[[str], None], fallando: dict) -> None:
    """Lo que una vuelta hace antes de pedir lo nuevo, cada paso en su `try` (C-0186).

    🔴 Regla dura 2, la mitad que faltaba: el relé no moría, pero se quedaba
    **sordo**. Pedir lo nuevo es lo último de la vuelta, y un paso de antes que
    fallaba siempre —una muestra cuya imagen ya no estaba— cortaba cada vuelta
    ahí: el proceso vivo, el canal mudo y nada en la pantalla que lo dijera.
    Igual que las mediciones del ciclo lento del snapshotter: que falle uno no
    deja sin hacer los demás.

    - Lo que depende de otro paso va con él en una sola entrada: si el primero
      falla, el segundo no corre sobre un estado a medias.
    - El fallo se apunta **una vez por racha** (`fallando`, que guarda quien
      llama entre vueltas: el tipo de error de cada paso). Uno por vuelta,
      cada dos segundos, taparía en el registro lo que sí hay que leer.
    - Sólo `Exception`, como el bucle: Ctrl-C no es un paso malo.
    """
    for clave, hacer in lista:
        try:
            hacer()
        except Exception as exc:  # noqa: BLE001 - un paso malo no deja sordo al relé
            tipo = type(exc).__name__
            if fallando.get(clave) != tipo:
                fallando[clave] = tipo
                _apuntar_fallo(nombre, registrar,
                               f"«{clave}» falló y la vuelta sigue (se apunta una vez): {exc!r}"[:500])
            continue
        fallando.pop(clave, None)


def correr(nombre: str, abrir_bot: Callable[[], Any],
           una_vuelta: Callable[[Any, int | None], int | None],
           registrar: Callable[[str], None], *,
           dormir: Callable[[float], Any] | None = None, vueltas: int | None = None) -> int | None:
    """El bucle de un relé. Aísla cada fallo para que no muera por una vuelta mala.

    Mismo criterio que el snapshotter (regla dura 2): un canal que se cae solo
    es peor que uno lento, porque su ausencia no se nota hasta que alguien
    llevaba media hora esperando una respuesta.

    - `abrir_bot()` se llama hasta que sale; sin token se vuelve a abrir en la
      vuelta siguiente, que es como se recoge un token arreglado sin reiniciar.
    - `una_vuelta(bot, offset)` devuelve el offset siguiente; el de una vuelta
      que falla se queda como estaba.
    - `registrar(texto)` apunta y guarda el fallo; si lanza, va a stderr.
    - `dormir` es `time.sleep` si no se da, buscado al llamar y no al
      importar: lo que un test ponga en su sitio llega al bucle.
    - `vueltas` acaba el bucle tras ese número y devuelve el offset: es lo que
      permite probarlo. El servicio lo deja en None, y no acaba.

    Sólo `Exception`: Ctrl-C no es una vuelta mala.
    """
    from . import telegram

    dormir = dormir or time.sleep
    offset: int | None = None
    bot_: Any = None
    hechas = 0
    while vueltas is None or hechas < vueltas:
        hechas += 1
        try:
            if bot_ is None:
                bot_ = abrir_bot()
            offset = una_vuelta(bot_, offset)
            dormir(PAUSA)
        except telegram.DosPollers as exc:
            # 🔴 Nunca en silencio. Reintentar callando hace que esto se vea
            # como «Telegram va lento» mientras dos procesos se roban los
            # mensajes de forma intermitente, y es el peor fallo de un canal.
            _apuntar_fallo(nombre, registrar, f"409, hay otro poller con el mismo token: {exc}")
            dormir(PAUSA_TRAS_FALLO)
        except telegram.SinToken as exc:
            _apuntar_fallo(nombre, registrar, f"sin token utilizable: {exc}")
            bot_ = None
            dormir(PAUSA_TRAS_FALLO)
        except telegram.TelegramCaido as exc:
            _apuntar_fallo(nombre, registrar, f"telegram no responde: {exc}")
            dormir(PAUSA_TRAS_FALLO)
        except Exception as exc:  # noqa: BLE001 - el bucle no puede morir
            _apuntar_fallo(nombre, registrar, f"vuelta fallida: {exc!r}")
            dormir(PAUSA_TRAS_FALLO)
    return offset


# ── El veredicto del token (C-0144, decisión 345) ────────────────────────────
#
# La web enseña si el canal tiene un token que sirve, y para saberlo lo abría:
# el token entraba un instante en la memoria de `hub-web`, que da una shell
# (reglas 8 y 22). Mirar sólo si el archivo existe perdía el diagnóstico de la
# clave vacía (`CLAVE=`), que se puso por un fallo real. Ahora lo lee quien lo
# usa —el relé, al abrir su bot— y deja escrito su veredicto, sin el token; la
# web lee el veredicto.

def _veredictos() -> Path:
    from . import config
    return config.HUB_HOME / "reles"


def anotar_token(rele: str, referencia: str, motivo: str | None) -> None:
    """El relé lo llama al abrir su bot: `motivo` None si el token sirve."""
    import json
    import time

    try:
        d = _veredictos()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{rele}.json.tmp"
        tmp.write_text(json.dumps({"referencia": referencia, "motivo": motivo, "t": time.time()}), encoding="utf-8")
        tmp.replace(d / f"{rele}.json")
    except OSError:
        pass   # sin veredicto, la web dice «sin comprobar»: no es motivo para no arrancar


def estado_token(rele: str, referencia: str, servicio: str) -> dict:
    """Lo que la web enseña del token, sin abrirlo.

    Un veredicto de otra referencia no vale: se cambió el puntero y el relé
    aún no lo ha leído.
    """
    import json

    try:
        v = json.loads((_veredictos() / f"{rele}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        v = None
    if not v or v.get("referencia") != referencia:
        return {"configurado": False, "referencia": referencia, "sin_comprobar": True,
                "detalle": f"`{servicio}` todavía no ha leído el token de este puntero (¿está arrancado?)"}
    if v.get("motivo"):
        return {"configurado": False, "referencia": referencia, "detalle": str(v["motivo"])}
    return {"configurado": True, "referencia": referencia, "detalle": "el relé leyó el token al arrancar"}
