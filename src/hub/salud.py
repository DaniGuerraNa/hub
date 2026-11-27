"""¿Está el hub en condiciones de hacer lo que promete? (decisión 289)

Lo pidió el dueño tras un fallo de un usuario: apagó el equipo, lo encendió al
día siguiente y no le volvió ninguna ventana. Desde fuera no se sabía si fue
porque el muestreo no corría, porque no había ningún slot marcado o por otra
cosa — y ninguna pantalla lo había advertido ANTES del apagón, que es cuando
tenía arreglo.

Cada comprobación dice tres cosas: qué mira, cómo está (`ok`, `aviso`, `mal`)
y qué hacer. Se miden de verdad (regla dura 13): lo que no se puede comprobar
desde aquí no sale con un «ok» puesto por defecto.

🔴 **El latido es del snapshotter, no de las muestras.** Sin tmux abierto —lo
normal nada más encender— el muestreo no escribe muestra (regla dura 4), así
que «la última muestra es de hace horas» no distingue un snapshotter muerto de
uno vivo esperando. Por eso el bucle deja su propio latido en cada vuelta.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

from . import acceso, config, copia_base, reloj, tmux

ARCHIVO_LATIDO = "latido-snapshotter.json"
# El muestreo late cada `INTERVALO_SEGUNDOS` (20 s). Unas cuantas vueltas
# perdidas son un ciclo lento o una base ocupada; minutos, que no corre.
AVISO_SEGUNDOS = 120
MAL_SEGUNDOS = 300
# El ciclo lento se pide cada diez minutos (C-0309). Media hora sin acabar una
# vuelta son tres perdidas; diez minutos en un paso, más de lo que ninguno
# tiene de presupuesto (el mayor, los repos, 45 s): está colgado, no lento.
LENTO_SIN_ACABAR = 30 * 60
LENTO_EN_UN_PASO = 10 * 60
# Cómo se le dice a la persona cada paso del ciclo lento. Uno que no esté
# aquí sale con su clave: mejor un nombre interno que callar cuál es.
PASOS_LENTOS = {
    "registro": "la lectura del registro de proyectos",
    "repos": "el respaldo de los repos",
    "servicios": "los contenedores",
    "indice": "el índice de búsqueda",
    "consumo": "el consumo",
    "maquina": "la salud del equipo",
    "copia_base": "la copia de la base",
    "version": "la búsqueda de versión nueva",
    "intercambio": "la limpieza de lo pegado en la terminal",
    "dictados": "la limpieza de dictados",
    "reuniones": "el procesado de las reuniones del puente",
}


def _servicios_del_hub() -> tuple[str, ...]:
    """Los que instala `scripts/lib/unidades.sh`, leídos de ahí (C-0115).

    Estaban también aquí y en `desinstalar.sh`, y ya habían divergido: un
    servicio nuevo que no se añade en los tres sitios se instala pero no se
    vigila, o se vigila pero no se quita. Que cada uno tenga su plantilla lo
    comprueba `tests/test_salud.py`."""
    texto = (config.RAIZ_REPO / "scripts" / "lib" / "unidades.sh").read_text(encoding="utf-8")
    m = re.search(r'^SERVICIOS_HUB="([^"]*)"', texto, re.M)
    if not m:
        raise RuntimeError("scripts/lib/unidades.sh no declara SERVICIOS_HUB")
    return tuple(m.group(1).split())


SERVICIOS = _servicios_del_hub()
# Los que el hub necesita siempre. Canal, encargos y secretario son opcionales: sólo
# cuentan si están habilitados.
IMPRESCINDIBLES = ("hub-web", "hub-snapshotter")


def latir(lento: dict | None = None) -> None:
    """Lo llama el bucle del snapshotter en cada vuelta, haya tmux o no.

    `lento` es el estado del ciclo lento (`snapshotter.CicloLento.estado`),
    que desde C-0309 corre en su hilo: viaja aquí para que `mediciones_lentas`
    lo juzgue sin que el snapshotter escriba en otro sitio. El latido no se
    pierde por él: si no cabe en JSON, sale sin él y se dice."""
    datos = {"en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pid": os.getpid()}
    texto = json.dumps(datos)
    if lento is not None:
        try:
            texto = json.dumps({**datos, "lento": lento})
        except (TypeError, ValueError) as exc:
            print(f"[salud] el estado del ciclo lento no se pudo escribir en el latido: {exc}",
                  flush=True)
    destino = config.HUB_HOME / ARCHIVO_LATIDO
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(texto)
    tmp.replace(destino)


def _latido() -> dict | None:
    try:
        datos = json.loads((config.HUB_HOME / ARCHIVO_LATIDO).read_text())
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _segundos_desde(valor: object, ahora: datetime) -> int | None:
    """Hace cuánto de una fecha del latido; None si no es una fecha."""
    try:
        cuando = datetime.fromisoformat(valor)  # type: ignore[arg-type]
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0, int((ahora - cuando).total_seconds()))


def _edad_latido(ahora: datetime | None = None) -> int | None:
    datos = _latido()
    return _segundos_desde((datos or {}).get("en"), ahora or datetime.now(timezone.utc))


def muestreo(ahora: datetime | None = None) -> dict:
    """Barato: un archivo. Es lo que se mira en TODAS las pantallas."""
    edad = _edad_latido(ahora)
    arreglo = ("systemctl --user restart hub-snapshotter   "
               "(y si no arranca: journalctl --user -u hub-snapshotter -n 40)")
    if edad is None:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "mal",
                "detalle": "El snapshotter no ha latido nunca: no está corriendo. Sin él no se "
                           "guarda qué ventanas tenías y al reiniciar no habrá nada que reabrir.",
                "arreglo": arreglo}
    if edad >= MAL_SEGUNDOS:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "mal",
                "detalle": f"El snapshotter no late desde hace {reloj.duracion(edad)}. Mientras no "
                           "corra, no se guarda qué ventanas tienes: si reinicias ahora, no se "
                           "podrán reabrir.",
                "arreglo": arreglo, "edad": edad}
    if edad >= AVISO_SEGUNDOS:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "aviso",
                "detalle": f"Último latido hace {reloj.duracion(edad)}: va con retraso.",
                "arreglo": arreglo, "edad": edad}
    return {"clave": "muestreo", "nombre": "Muestreo", "estado": "ok",
            "detalle": f"Late cada {config.INTERVALO_SEGUNDOS} s (último hace {reloj.duracion(edad)}).",
            "edad": edad}


def mediciones_lentas(ahora: datetime | None = None) -> dict | None:
    """Cómo va el ciclo lento, por lo que el snapshotter dejó en su latido (C-0309).

    Desde que corre en su hilo, colgarse en un `stat` sobre el disco de
    Windows ya no para el latido: el hub parece sano y el respaldo, el consumo
    y la salud del equipo se quedan con cifras de hace horas. Esto es lo que
    lo dice. Sólo en pantalla: no es una clase de `avisos.CLASES` (regla dura
    3), no sale al teléfono.

    None si no hay nada que juzgar (regla dura 13): sin latido reciente —eso
    ya lo dice «Muestreo»—, o con un snapshotter de antes de esto, que no
    cuenta nada del ciclo lento.
    """
    ahora = ahora or datetime.now(timezone.utc)
    datos = _latido() or {}
    edad = _segundos_desde(datos.get("en"), ahora)
    lento = datos.get("lento")
    if edad is None or edad >= MAL_SEGUNDOS or not isinstance(lento, dict):
        return None
    acabo = _segundos_desde(lento.get("acabo"), ahora)
    # Si nunca acabó una vuelta, «sin acabar» cuenta desde que arrancó.
    sin_acabar = acabo if acabo is not None else _segundos_desde(lento.get("desde"), ahora)
    if sin_acabar is None:
        return None
    paso = lento.get("paso") if isinstance(lento.get("paso"), str) else None
    en_el_paso = _segundos_desde(lento.get("paso_desde"), ahora) if paso else None
    nombre_paso = PASOS_LENTOS.get(paso or "", f"«{paso}»")
    duro = lento.get("duro") if isinstance(lento.get("duro"), (int, float)) else None

    fila = {"clave": "lento", "nombre": "Mediciones lentas"}
    diario = "journalctl --user -u hub-snapshotter -n 40"
    arreglo = f"systemctl --user restart hub-snapshotter   (y el porqué: {diario})"
    de_que = "del respaldo, los contenedores, el consumo y la salud del equipo"
    if en_el_paso is not None and en_el_paso >= LENTO_EN_UN_PASO:
        return {**fila, "estado": "aviso", "arreglo": arreglo,
                "detalle": f"Llevan {reloj.duracion(en_el_paso)} con {nombre_paso} y no acaba: mientras "
                           f"tanto no se mide lo demás, y las cifras {de_que} se quedan "
                           "viejas. El muestreo de ventanas no depende de esto y sigue."}
    fallo = lento["fallo"] if isinstance(lento.get("fallo"), str) and lento["fallo"] else None
    if sin_acabar >= LENTO_SIN_ACABAR and lento.get("corriendo") is not True and not fallo:
        # Ni hay una en marcha ni la última falló: nadie la ha pedido aún. Es
        # lo que se ve al despertar el equipo de una suspensión —el latido es
        # de ahora y la última vuelta, de anoche— y se arregla solo: mandar
        # reiniciar el muestreo aquí era un consejo que no hacía falta seguir.
        cuando = (f"La última vuelta acabó hace {reloj.duracion(sin_acabar)} y no hay ninguna en marcha: "
                  "es lo normal si el equipo ha estado suspendido." if acabo is not None else
                  f"El muestreo arrancó hace {reloj.duracion(sin_acabar)}, todavía no ha acabado ninguna "
                  "vuelta y no hay ninguna en marcha.")
        return {**fila, "estado": "aviso",
                "detalle": f"{cuando} Las cifras {de_que} son de antes y se vuelven a medir en "
                           "la próxima vuelta, que se pide sola cada diez minutos."}
    if sin_acabar >= LENTO_SIN_ACABAR:
        detalle = (f"Llevan {reloj.duracion(sin_acabar)} sin terminar una vuelta: las cifras {de_que} "
                   "son de entonces.")
        if fallo:
            detalle += f" La última falló: {fallo}"
        return {**fila, "estado": "aviso", "detalle": detalle, "arreglo": arreglo}
    if lento.get("dentro") is True:
        return {**fila, "estado": "aviso", "arreglo": arreglo,
                "detalle": "Su hilo no arranca, así que se miden dentro del muestreo: cada "
                           "diez minutos la muestra de ventanas, los mensajes programados y "
                           "el orquestador esperan a que acaben."}
    fallaron = lento.get("fallaron")
    if isinstance(fallaron, dict) and fallaron:
        # La vuelta acabó, pero cada paso va en su `try`: pueden haber lanzado
        # todos y «acabó hace 2 min» sería verdad sobre cifras que nadie
        # refrescó. Aviso y no «mal»: el muestreo de ventanas no depende de esto.
        nombres = [PASOS_LENTOS.get(str(clave), f"«{clave}»") for clave in fallaron]
        lista = nombres[0] if len(nombres) == 1 else f"{', '.join(nombres[:-1])} y {nombres[-1]}"
        return {**fila, "estado": "aviso", "arreglo": f"{diario}   (ahí está el porqué de cada uno)",
                "detalle": f"En la última vuelta no se pudo medir: {lista}. Lo que ves de eso "
                           "es de la última vez que salió bien."}
    if acabo is None:
        return {**fila, "estado": "ok",
                "detalle": "Todavía no ha acabado la primera vuelta desde que arrancó el "
                           f"muestreo, hace {reloj.duracion(sin_acabar)}."}
    detalle = f"Se miden aparte del muestreo. La última vuelta acabó hace {reloj.duracion(acabo)}"
    if duro is not None:
        detalle += f" y tardó {reloj.duracion(int(duro))}"
    return {**fila, "estado": "ok", "detalle": detalle + "."}


def _tmux() -> dict:
    abierto = tmux.servidor_pid() is not None
    if abierto:
        return {"clave": "tmux", "nombre": "tmux", "estado": "ok",
                "detalle": "Hay un servidor de tmux con ventanas que vigilar."}
    return {"clave": "tmux", "nombre": "tmux", "estado": "aviso",
            "detalle": "No hay tmux abierto. Es normal nada más encender el equipo; si tenías "
                       "slots persistentes, Panorama te ofrece reabrirlos.",
            "arreglo": "Panorama → «Reabrir tus slots persistentes»"}


def _restauracion(slots: list[dict]) -> dict:
    """`slots` son los activos, leídos por `api.py` (una sola costura, C-0056)."""
    activos = len(slots)
    marcados = sum(1 for s in slots if s.get("restaurar"))
    if not activos:
        return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "ok",
                "detalle": "Todavía no hay slots: no hay nada que reabrir."}
    if not marcados:
        return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "aviso",
                "detalle": f"Ninguno de tus {activos} slots es persistente: si reinicias el "
                           "equipo, no habrá nada que reabrir.",
                "arreglo": "En Trabajo, en la cabecera de cada slot que quieras conservar, "
                           "pulsa «↻ No persistente» para que pase a «↻ Persistente»"}
    return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "ok",
            "detalle": f"{marcados} de {activos} slots son persistentes (marcados con ↻)."}


def _systemctl(*args: str) -> str | None:
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip()


def _orden(*args: str, timeout: float = 30) -> tuple[int, str]:
    """`systemctl --user` para lo que actúa: con su código y lo que dijo.

    `_systemctl` sirve para preguntar y se traga ambas cosas; aquí hacen falta,
    porque «no se encendió» sin el porqué («Unit not found») no deja arreglar
    nada."""
    if not shutil.which("systemctl"):
        return 127, "no está systemctl"
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"systemctl no contestó en {timeout:.0f} s"
    except OSError as exc:
        return 126, str(exc)
    return r.returncode, (r.stderr or r.stdout).strip()


def hay_systemd_de_usuario() -> bool:
    """Si hay un systemd de usuario que gestione los servicios del hub.

    La única pregunta (C-0115; la usa también `actualizacion`). Por el código
    de salida de `show-environment`: con `systemctl` instalado y sin sesión de
    usuario, la salida vacía se tomaba por «sí» y web y muestreo salían como
    parados en vez de decir que no hay systemd."""
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _estado(nombre: str) -> dict:
    return {"activo": _systemctl("is-active", nombre) or "",
            "habilitado": _systemctl("is-enabled", nombre) == "enabled"}


def estado_servicio(nombre: str) -> dict | None:
    """Cómo está un servicio del hub: `activo` es lo que dice `is-active`
    (`active`, `inactive`, `failed`, `activating`…) y `habilitado`, si arranca
    solo al encender. None si no hay systemd de usuario: ahí no hay servicio
    que mirar, y «parado» sería mentira."""
    if not hay_systemd_de_usuario():
        return None
    return _estado(nombre)


def _latido_secretario() -> str | None:
    from .secretario import memoria
    try:
        return memoria.leer_sin_abrir("latido")
    except sqlite3.Error:   # sin base aún: todavía no ha latido nunca
        return None


def _latido_snapshotter() -> str | None:
    en = (_latido() or {}).get("en")
    return en if isinstance(en, str) else None


# La señal de vida de cada servicio que la tiene: cuándo latió por última vez,
# como la guarda (`reloj.ahora()`). Arrancado no es funcionar (151): lo que
# vale es una señal posterior a encenderlo o reiniciarlo. La web se mira
# contestando (`actualizar.sh`, `instalar.sh`); canal y encargos no tienen.
SENALES = {
    "hub-snapshotter": _latido_snapshotter,
    "hub-secretario": _latido_secretario,
}

# Lo que la web puede encender (decisión 400), por nombre exacto: nunca viene de
# la petición, como los contenedores (50). Cada uno con su nombre para la
# persona y lo que se corre a mano sin systemd; su señal, en `SENALES`. Canal y
# encargos no: sin su token sólo sabrían apuntar fallos (`instalar.sh`).
ENCENDIBLES = {
    "hub-secretario": ("El secretario", "uv run python -m hub.secretario"),
}
# La primera vez `uv run` prepara el entorno y puede pasar de 20 s.
ESPERA_SENAL = 30


def _posterior(valor: object, desde) -> bool:
    """Si una señal es de `desde` o después. Una que no se entiende no cuenta:
    mejor «aún no da señales» que un 500 en mitad de encender."""
    try:
        return bool(valor) and reloj.instante(valor) >= desde  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def esperar_senal(nombre: str, desde: str, espera: float = ESPERA_SENAL) -> str:
    """Espera hasta `espera` segundos a que `nombre` dé una señal de vida de
    `desde` o después, y dice cómo quedó (C-0448):

    - `ok`: dio la señal;
    - `sin-senal`: sigue en marcha (`is-active`) pero aún no late;
    - `caido`: ni late ni está en marcha (con `Restart=always`, uno que
      revienta al arrancar pasa la espera entre intentos en `activating`);
    - `sin-medir`: no tiene señal propia (canal, encargos) y está en marcha.
      No se espera por nada: se mira una vez, así que quien llama deja pasar
      unos segundos desde el arranque.

    `desde` es una fecha como las de `reloj.ahora()`. La usan `encender`,
    después de su `enable --now`, y `actualizar.sh` tras reiniciar
    (`python -m hub.salud senal`). Sólo pregunta: no acciona nada.
    """
    senal = SENALES.get(nombre)
    if senal is None:
        return "sin-medir" if _systemctl("is-active", nombre) == "active" else "caido"
    desde_t = reloj.instante(desde)
    limite = time.monotonic() + espera
    while True:
        if _posterior(senal(), desde_t):
            return "ok"
        if time.monotonic() >= limite:
            break
        time.sleep(1)
    return "sin-senal" if _systemctl("is-active", nombre) == "active" else "caido"


def encender(nombre: str, espera: float | None = None) -> tuple[str, str]:
    """Enciende un servicio opcional del hub y lo deja encendido al reiniciar
    (`enable --now`), y dice cómo quedó: `encendido` (ya da señales),
    `sin-senal` (arrancó pero aún no late) o `no` (no arrancó o se cae).

    Sólo los de `ENCENDIBLES` (decisión 400): un nombre fuera de la lista es
    un error de quien llama, no algo que se intente. Se da por encendido cuando
    su señal es **posterior al clic**, no cuando `systemctl` devuelve 0: eso
    dice que la orden salió (151, como `panico.reiniciar`). Sin systemd no se
    lanza el proceso desde aquí —colgaría del servicio que lo lanza y nadie lo
    levantaría al caerse (153, 344)—: se dice el comando.
    """
    if nombre not in ENCENDIBLES:
        raise ValueError(f"{nombre} no se enciende desde el hub")
    quien, a_mano = ENCENDIBLES[nombre]
    if not hay_systemd_de_usuario():
        return "no", (f"Sin systemd de usuario no se enciende desde aquí. En una terminal, en la "
                      f"carpeta del hub: {a_mano}")
    antes = reloj.ahora()
    codigo, dijo = _orden("enable", "--now", nombre)
    if codigo != 0:
        return "no", f"{quien} no se encendió: {(dijo or f'systemctl salió con {codigo}').rstrip('.')}."
    como = esperar_senal(nombre, antes, ESPERA_SENAL if espera is None else espera)
    if como == "ok":
        return "encendido", f"{quien} está en marcha, y seguirá encendido cuando reinicies el equipo."
    if como != "sin-senal":
        return "no", (f"{quien} se encendió pero se cae al arrancar. Lo que dice al caerse: "
                      f"journalctl --user -u {nombre} -n 40")
    return "sin-senal", (f"{quien} está arrancando pero aún no da señales; la primera vez puede tardar "
                         f"un minuto. Si no se pone en verde, mira systemctl --user status {nombre}")


def _servicios() -> list[dict]:
    if not hay_systemd_de_usuario():
        return [{"clave": "servicios", "nombre": "Servicios", "estado": "aviso",
                 "detalle": "No hay systemd de usuario: el hub no arranca solo ni se levanta "
                            "si se cae. Lo arrancas tú con scripts/arrancar.sh.",
                 "arreglo": "INSTALAR.md, «Servicios»"}]
    salida = []
    for nombre in SERVICIOS:
        e = _estado(nombre)
        habilitado, activo = e["habilitado"], e["activo"] == "active"
        if not habilitado and nombre not in IMPRESCINDIBLES:
            continue   # canal o encargos sin configurar: no es un fallo
        if activo and habilitado:
            estado, detalle = "ok", "En marcha, y arranca solo."
        elif activo:
            estado, detalle = "aviso", "En marcha, pero no arranca solo al encender."
        else:
            estado, detalle = "mal", "Parado."
        salida.append({"clave": f"servicio:{nombre}", "nombre": nombre, "estado": estado,
                       "detalle": detalle,
                       "arreglo": None if estado == "ok" else
                       f"systemctl --user enable --now {nombre}"})
    return salida


def _linger() -> dict | None:
    usuario = os.environ.get("USER") or ""
    if not usuario or not shutil.which("loginctl"):
        return None
    try:
        r = subprocess.run(["loginctl", "show-user", usuario, "-p", "Linger"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if "Linger=yes" in r.stdout:
        return {"clave": "linger", "nombre": "Seguir vivo sin terminal", "estado": "ok",
                "detalle": "El hub sigue corriendo aunque cierres todas las terminales."}
    if "Linger=no" in r.stdout:
        return {"clave": "linger", "nombre": "Seguir vivo sin terminal", "estado": "aviso",
                "detalle": "Al cerrar la última terminal se apagan los servicios del hub, y el "
                           "muestreo con ellos.",
                "arreglo": f"loginctl enable-linger {usuario}"}
    return None


def _copia() -> dict:
    e = copia_base.estado()
    if not e["copias"]:
        return {"clave": "copia", "nombre": "Copia de la base", "estado": "aviso",
                "detalle": "Todavía no hay ninguna copia de hub.db (se hace sola una vez al día).",
                "arreglo": "Mira que el muestreo corra: la copia la hace él."}
    if e["vieja"]:
        return {"clave": "copia", "nombre": "Copia de la base", "estado": "aviso",
                "detalle": f"La última copia de hub.db es del {e['ultima'].replace('T', ' ')}.",
                "arreglo": "Mira que el muestreo corra: la copia la hace él."}
    return {"clave": "copia", "nombre": "Copia de la base", "estado": "ok",
            "detalle": f"Última del {e['ultima'].replace('T', ' ')}, {e['copias']} guardadas."}


def _copia_secretario() -> dict | None:
    """La copia diaria de la memoria del secretario, con el mismo umbral (C-0282).

    Es la base que más vale —entera, no se reconstruye (decisión 299)— y la
    que más crece, y su copia la hace `hub-secretario`: si dejaba de hacerse,
    sólo quedaba en su bitácora. Sin secretario en uso no se echa en falta.
    Se dice aquí, en Máquina y en `/respaldo`; no es un aviso que salga solo
    (`avisos.CLASES` es lista cerrada, regla dura 3).
    """
    from .secretario import memoria
    if not memoria.existe():
        return None
    nombre = "Copia de la memoria del secretario"
    arreglo = "Mira que el secretario corra (hub-secretario): la copia la hace él."
    e = copia_base.estado(prefijo=copia_base.PREFIJO_SECRETARIO)
    if not e["copias"]:
        return {"clave": "copia-secretario", "nombre": nombre, "estado": "aviso",
                "detalle": "Todavía no hay ninguna copia de memoria.db (se hace sola una vez al día).",
                "arreglo": arreglo}
    if e["vieja"]:
        return {"clave": "copia-secretario", "nombre": nombre, "estado": "aviso",
                "detalle": f"La última copia de memoria.db es del {e['ultima'].replace('T', ' ')}.",
                "arreglo": arreglo}
    return {"clave": "copia-secretario", "nombre": nombre, "estado": "ok",
            "detalle": f"Última del {e['ultima'].replace('T', ' ')}, {e['copias']} guardadas."}


def _con_nombre_remoto() -> bool:
    """Si se entra desde otro aparato: sólo entonces importa volver sin nadie."""
    # Roto el archivo, valen sólo los de casa: eso ya lo dice /acceso.
    return any(h not in acceso.HOSTS_LOCALES for h in acceso.hosts(tolerante=True))


def _desatendido(medidas: dict[str, dict]) -> list[dict]:
    """Lo que hace falta para que un apagón tenga vuelta sin nadie delante (C-0214).

    Lo midió el ciclo lento (`maquina._tailscale` y `maquina._arranque`); aquí
    sólo se juzga. Lo que no se pudo medir no sale: un «ok» puesto por defecto
    es justo lo que esta pantalla no hace. Y sólo con un nombre remoto en
    `acceso.yml`: quien usa el hub delante de la máquina inicia sesión él.
    """
    if not _con_nombre_remoto():
        return []

    # 🔴 Sólo cuenta lo de la última vuelta lenta. Una medida que dejó de
    # poderse tomar conserva la anterior (`maquina`), y con Tailscale parado o
    # desinstalado eso enseñaba su último «bien» justo cuando no se puede
    # entrar. El SAI se mide aparte, cada minuto: no marca la vuelta.
    vuelta = max((m.get("medido_en") or "" for k, m in medidas.items()
                  if not k.startswith("ups.")), default="")

    def vieja(clave: str) -> bool:
        m = medidas.get(clave)
        return bool(m) and (m.get("medido_en") or "") < vuelta

    def medida(clave: str) -> dict | None:
        m = medidas.get(clave)
        return m if m and m.get("valor") is not None and not vieja(clave) else None

    nombre = "Volver sola tras un apagón"
    salida = []
    if vieja("desatendido.serve") or vieja("desatendido.tailscale"):
        salida.append({"clave": "desatendido:sin-medir", "nombre": "Entrar desde fuera",
                       "estado": "aviso",
                       "detalle": "En la última medición no se pudo leer Tailscale. Si está "
                                  "parado, desde otro aparato no se entra.",
                       "arreglo": "En la máquina del hub: tailscale status"})
    if serve := medida("desatendido.serve"):
        if serve["valor"]:
            salida.append({"clave": "desatendido:serve", "nombre": "Entrar desde fuera",
                           "estado": "ok",
                           "detalle": f"La red privada lleva al hub ({serve['texto']})."})
        else:
            salida.append({"clave": "desatendido:serve", "nombre": "Entrar desde fuera",
                           "estado": "mal",
                           "detalle": "tailscale serve no lleva al hub: desde otro aparato "
                                      "no se llega, aunque el nombre esté en Acceso.",
                           "arreglo": f"En la máquina del hub: tailscale serve --bg {config.WEB_PORT}"})
    if ts := medida("desatendido.tailscale"):
        if ts["valor"]:
            salida.append({"clave": "desatendido:tailscale", "nombre": nombre, "estado": "ok",
                           "detalle": "Tailscale conecta al encender aunque nadie inicie "
                                      "sesión en Windows."})
        else:
            salida.append({"clave": "desatendido:tailscale", "nombre": nombre, "estado": "aviso",
                           "detalle": "Tailscale sólo conecta con la sesión de Windows "
                                      "iniciada: tras un apagón no se podrá entrar desde fuera "
                                      "hasta que alguien entre en Windows.",
                           "arreglo": "En Windows, en PowerShell: tailscale set --unattended=true"})
    if tarea := medida("desatendido.tarea"):
        if tarea["valor"]:
            salida.append({"clave": "desatendido:tarea", "nombre": nombre, "estado": "ok",
                           "detalle": f"Al encender, la tarea «{tarea['texto']}» levanta WSL "
                                      "sin que nadie inicie sesión."})
        else:
            salida.append({"clave": "desatendido:tarea", "nombre": nombre, "estado": "aviso",
                           "detalle": "Al encender, WSL —y el hub con él— no arranca hasta que "
                                      "alguien inicia sesión en Windows.",
                           "arreglo": "scripts/arrancar-sin-sesion.ps1, en PowerShell "
                                      "como administrador (INSTALAR.md, «El hub en una "
                                      "máquina aparte»)"})
    if susp := medida("desatendido.suspender"):
        if not susp["valor"]:
            salida.append({"clave": "desatendido:suspender", "nombre": "No suspenderse",
                           "estado": "ok", "detalle": "Con corriente, Windows no se suspende."})
        else:
            salida.append({"clave": "desatendido:suspender", "nombre": "No suspenderse",
                           "estado": "aviso",
                           "detalle": f"Con corriente, Windows se suspende tras "
                                      f"{reloj.duracion(int(susp['valor']))} sin nadie delante, y "
                                      "el hub deja de contestar.",
                           "arreglo": "En Windows: powercfg /change standby-timeout-ac 0"})
    return salida


def revisar(slots: list[dict], medidas: dict[str, dict] | None = None) -> list[dict]:
    """Todas las comprobaciones, lo que peor está primero. `slots`, los activos;
    `medidas`, lo último que midió el ciclo lento (`maquina.ultimas`)."""
    revisiones = [muestreo(), _tmux(), _restauracion(slots), *_servicios(),
                  *_desatendido(medidas or {})]
    for extra in (mediciones_lentas(), _linger(), _copia(), _copia_secretario()):
        if extra:
            revisiones.append(extra)
    orden = {"mal": 0, "aviso": 1, "ok": 2}
    return sorted(revisiones, key=lambda r: orden[r["estado"]])


def main(argv: list[str]) -> int:
    """`python -m hub.salud senal <servicio> --desde <fecha> [--espera <s>]`.

    Lo corre `actualizar.sh` tras reiniciar cada servicio (C-0448) y escribe
    una sola palabra, la de `esperar_senal`: el guion decide qué es fallo y
    qué aviso. El servicio tiene que ser uno del hub (`SERVICIOS`)."""
    lector = argparse.ArgumentParser(prog="python -m hub.salud")
    ordenes = lector.add_subparsers(dest="orden", required=True)
    senal = ordenes.add_parser("senal", help="espera la señal de vida de un servicio")
    senal.add_argument("servicio", choices=SERVICIOS)
    senal.add_argument("--desde", required=True, help="fecha ISO: sólo cuenta una señal posterior")
    senal.add_argument("--espera", type=float, default=ESPERA_SENAL, help="segundos")
    args = lector.parse_args(argv)
    try:
        reloj.instante(args.desde)
    except ValueError:
        lector.error(f"--desde no es una fecha: {args.desde}")
    print(esperar_senal(args.servicio, args.desde, args.espera))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
