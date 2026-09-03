"""Terminal embebida: un `tmux attach` dentro de un PTY, servido por WebSocket.

No construimos un terminal: tmux ya hospeda los procesos, así que esto sólo se
engancha a lo que ya está corriendo y transporta bytes. El proceso sigue vivo
aunque cierres la pestaña — igual que si te desatacharas.

🔴 Este módulo da acceso de shell a quien alcance el puerto. La UI escucha SOLO
en 127.0.0.1. Cuando el hub se mueva a un VPS, este endpoint NO puede exponerse
sin autenticación (ver regla dura 8 de CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import select
import signal
import subprocess
import struct
import termios
import time
import uuid

from . import tmux

# Sesión espejo por cada sesión real. Existe por una razón concreta: tmux
# dimensiona una sesión al cliente más pequeño atacado, así que si el navegador
# se atacara directo, tu Windows Terminal encogería la ventana (y al revés).
# Una sesión agrupada comparte las mismas ventanas pero tiene su propio tamaño.
PREFIJO_ESPEJO = tmux.PREFIJO_ESPEJO

# La validación vive en el adaptador: es la última frontera antes de tmux.
DestinoInvalido = tmux.DestinoInvalido

# Lo que se espera a que el PTY admita más bytes cuando no hay bucle de eventos
# que avise. Un `tmux attach` vivo drena en microsegundos; si tarda un segundo
# es que no está leyendo, y entonces vale más cortar que colgar la petición.
ESPERA_HUECO = 1.0


def sesiones_disponibles() -> list[dict]:
    """Sesiones reales, sin las espejo que crea el propio hub."""
    vistas: dict[str, dict] = {}
    for p in tmux.listar_paneles():
        nombre = p["session"]
        if nombre.startswith(PREFIJO_ESPEJO):
            continue
        entrada = vistas.setdefault(nombre, {"session": nombre, "paneles": 0, "etiquetas": []})
        entrada["paneles"] += 1
        entrada["etiquetas"].append(
            tmux.inferir_etiqueta(p["titulo"], p["cwd"], p["comando"])
        )
    return sorted(vistas.values(), key=lambda s: s["session"])


def _sesiones_espejo() -> list[tuple[str, int, int]]:
    """(nombre, clientes atacados, epoch de creación) de las sesiones espejo."""
    try:
        crudo = tmux._correr(
            ["list-sessions", "-F",
             "#{session_name}\t#{session_attached}\t#{session_created}"]
        )
    except (tmux.TmuxNoDisponible, RuntimeError):
        return []

    encontradas = []
    for linea in crudo.splitlines():
        partes = linea.split("\t")
        if len(partes) < 3 or not partes[0].startswith(PREFIJO_ESPEJO):
            continue
        try:
            encontradas.append((partes[0], int(partes[1] or 0), int(partes[2] or 0)))
        except ValueError:
            continue
    return encontradas


def limpiar_espejos_huerfanos(gracia: int = 60) -> list[str]:
    """Barre espejos sin clientes.

    El periodo de gracia evita la carrera obvia: un espejo recién creado está
    detached durante los milisegundos que tarda el attach, y sin gracia otra
    pestaña abriéndose al mismo tiempo se lo llevaría por delante.
    """
    ahora = int(time.time())
    barridas = []
    for nombre, clientes, creada in _sesiones_espejo():
        if clientes == 0 and ahora - creada > gracia:
            destruir_espejo(nombre)
            barridas.append(nombre)
    return barridas


def dimensionar_al_espectador(espejo: str) -> None:
    """Que cada ventana se ajuste a la sesión que la está mirando.

    🔴 Sin esto se PIERDE TEXTO, y de la peor manera: en silencio. tmux trae
    `window-size latest`, así que una ventana conserva el ancho del último
    cliente que la tocó. Medido: con un solo cliente de 168 columnas, `work:0`
    estaba a 168 y `work:1` a 172. Al saltar a esa pestaña, tmux seguía
    contando 172 columnas y el navegador sólo pintaba 168 — «cuan» donde decía
    «cuando»—, y volvía al redimensionar porque eso sí forzaba el reajuste.

    Va **por ventana y sin `-g`**. Con `-g` la opción es global de todo el
    servidor de tmux: la primera versión de este arreglo se la dejó puesta al
    usuario en todas sus sesiones, que es justo el tipo de efecto lateral que el
    hub no debe tener sobre lo que no le pertenece.

    Que la opción viva en la ventana —compartida con la sesión original— es
    correcto y no un efecto colateral: significa «dimensiónate a quien te está
    viendo», y cuando quien la vea sea la terminal nativa, se ajustará a ella.
    """
    # 🔴 Pero NO si otra terminal está mirando la misma ventana.
    #
    # Encoger una ventana **trunca de forma irreversible** lo ya escrito: tmux
    # no reenvuelve el historial, lo recorta. Medido en una máquina real:
    # una ventana estaba a 237 columnas porque su Windows Terminal la tenía
    # abierta, y la vista del hub daba 168. Con el ajuste puesto, abrir esa
    # sesión en el navegador se llevaba por delante el final de cada línea ya
    # escrita — y al volver a su terminal el texto seguía perdido.
    #
    # Así que el ajuste sólo se aplica cuando el hub es el único espectador.
    # Con alguien más mirando, se prefiere recortar la VISTA —que es reversible,
    # basta bajar la letra— antes que romper el CONTENIDO.
    if _hay_otro_espectador(espejo):
        return
    try:
        for v in tmux.listar_ventanas(espejo):
            tmux._correr([
                "set-window-option", "-t", f"={espejo}:{int(v['indice'])}",
                "aggressive-resize", "on",
            ])
    except (RuntimeError, ValueError, tmux.TmuxNoDisponible):
        pass  # sin esto se ve mal, pero la terminal sigue siendo usable


def _hay_otro_espectador(espejo: str) -> bool:
    """Si alguien que no es este espejo está atacado a las mismas ventanas.

    Las sesiones agrupadas comparten ventanas, así que cualquier cliente de
    cualquiera de ellas cuenta. Ante la duda —tmux no responde— se contesta que
    sí: no encoger es lo seguro.
    """
    try:
        crudo = tmux._correr(
            ["list-clients", "-F", "#{client_session}\t#{session_group}"]
        )
        grupo_mio = tmux._correr(
            ["display-message", "-p", "-t", f"={espejo}", "#{session_group}"]
        ).strip()
    except (RuntimeError, tmux.TmuxNoDisponible):
        return True

    for linea in crudo.splitlines():
        partes = linea.split("\t")
        if len(partes) < 2 or partes[0] == espejo:
            continue
        if partes[1] and partes[1] == grupo_mio:
            return True
    return False


def crear_espejo(session: str, ventana: int | None = None) -> str:
    """Crea una sesión agrupada propia de esta conexión.

    Una por pestaña y no una por sesión: así dos vistas abiertas del mismo
    trabajo tampoco se encogen entre sí.

    `ventana` posiciona la vista sin tocar la sesión original: las sesiones
    agrupadas comparten ventanas pero cada una tiene su ventana activa propia.
    Es lo que permite "abrir este slot" sin mover de sitio a quien esté atacado
    en la terminal nativa.
    """
    tmux.validar_sesion(session)

    limpiar_espejos_huerfanos()
    nombre = f"{PREFIJO_ESPEJO}{session}-{uuid.uuid4().hex[:6]}"
    # -t agrupa con la sesión origen: mismas ventanas, tamaño independiente.
    tmux._correr(["new-session", "-d", "-t", session, "-s", nombre])

    dimensionar_al_espectador(nombre)

    # La rueda del ratón, que es como el usuario hace scroll. Va SOLO en el espejo —
    # `mouse` es una opción de sesión—, así que su terminal nativa no cambia de
    # comportamiento. Con esto la rueda entra en el copy-mode de tmux y recorre
    # su historial, que es lo que se quiere ver.
    # Sin `=`: `set-option` es el único de estos comandos que NO acepta ese
    # prefijo de coincidencia exacta —«no such session: =hub-…»— y el `except`
    # se lo tragaba, así que la rueda no funcionaba y nada lo decía. El nombre
    # es seguro igualmente: lo compone este módulo y ya pasó por `validar_sesion`.
    try:
        tmux._correr(["set-option", "-t", nombre, "mouse", "on"])
    except (RuntimeError, tmux.TmuxNoDisponible) as exc:
        # En voz alta: un fallo mudo aquí se manifiesta como «el scroll no va»,
        # que es exactamente lo que costó encontrar.
        print(f"[terminal] no se pudo activar la rueda en {nombre}: {exc}", flush=True)

    if ventana is not None:
        try:
            tmux.seleccionar_ventana(nombre, ventana)
        except (RuntimeError, ValueError, tmux.TmuxNoDisponible):
            pass  # la ventana pudo cerrarse; el attach sigue siendo válido
    return nombre


def destruir_espejo(nombre: str) -> None:
    if not nombre.startswith(PREFIJO_ESPEJO):
        return
    try:
        tmux._correr(["kill-session", "-t", f"={nombre}"])
    except (RuntimeError, tmux.TmuxNoDisponible, OSError, subprocess.SubprocessError):
        # También `TimeoutExpired`: `tmux._correr` lleva `timeout=10` y esa
        # excepción no la cubría ninguna de las dos ramas de arriba. Esto se
        # llama desde el `finally` del WebSocket, así que dejarla escapar
        # significaría no limpiar el espejo —y encima con la petición ya
        # cerrada, sin nadie a quien contárselo.
        pass


def _redimensionar(fd: int, filas: int, columnas: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", filas, columnas, 0, 0))


class Adjunto:
    """Un `tmux attach` vivo, con su PTY."""

    def __init__(self, espejo: str, filas: int = 40, columnas: int = 120):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # pragma: no cover - proceso hijo
            os.environ["TERM"] = "xterm-256color"
            # Por `orden_base()` y no `["tmux", ...]` a pelo: si el hub corre
            # contra un servidor de tmux aparte (`HUB_TMUX_SOCKET`), atacarse al
            # servidor por defecto abriría una terminal a las sesiones de otro.
            orden = [*tmux.orden_base(), "attach", "-t", espejo]
            os.execvp(orden[0], orden)
            os._exit(1)
        _redimensionar(self.fd, filas, columnas)
        os.set_blocking(self.fd, False)
        self._pendiente = bytearray()
        self._esperando = False

    def escribir(self, datos: bytes) -> None:
        """Escribe TODO lo que le den, aunque no quepa de una vez.

        🔴 El fd es NO BLOQUEANTE, así que `os.write` mete lo que cabe en el
        buffer del PTY y **devuelve cuánto**: sin mirar ese retorno, el resto se
        tira en silencio. Medido en un PTY igual que este: de 16.000 bytes
        entraron 11.776 y se perdieron 4.224, y la llamada siguiente dio
        `BlockingIOError` — que se atrapaba con el resto de `OSError` y se
        ignoraba, así que el trozo siguiente desaparecía entero.

        Se ve pegando un texto largo en la terminal web: llega cortado a mitad
        de palabra, en varios sitios y no sólo al final, porque cada trozo del
        pegado pierde su cola. Con textos cortos no pasa nunca — que es
        justamente lo que lo hacía parecer cosa del portapapeles.
        """
        self._pendiente += datos
        self._vaciar()

    def _vaciar(self) -> None:
        """Empuja lo pendiente, y lo que no quepa queda para el siguiente hueco.

        El orden se conserva porque todo pasa por la misma cola: mientras haya
        pendiente, lo nuevo se encola detrás en vez de adelantarse.
        """
        while self._pendiente:
            try:
                escritos = os.write(self.fd, self._pendiente)
            except BlockingIOError:
                escritos = 0
            except OSError:
                # El otro extremo se fue: lo pendiente ya no tiene destino.
                self._pendiente.clear()
                break
            if escritos:
                del self._pendiente[:escritos]
                continue
            if self._aplazar():
                return  # se sigue solo cuando el PTY acepte más
            # Sin bucle de eventos (tests, usos síncronos) se espera aquí, con
            # tope: colgar el servidor es peor que perder un pegado.
            if not select.select([], [self.fd], [], ESPERA_HUECO)[1]:
                break
        self._soltar_espera()

    def _aplazar(self) -> bool:
        """Pide que nos avisen cuando el PTY vuelva a admitir bytes.

        Con `add_writer`, simétrico al `add_reader` de `bombear()`: esto corre
        dentro del manejador del WebSocket, y esperar ahí a que tmux drene
        pararía el servidor entero.
        """
        try:
            bucle = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if not self._esperando:
            bucle.add_writer(self.fd, self._vaciar)
            self._esperando = True
        return True

    def _soltar_espera(self) -> None:
        if not self._esperando:
            return
        self._esperando = False
        try:
            asyncio.get_running_loop().remove_writer(self.fd)
        except (RuntimeError, OSError, ValueError):
            pass

    def redimensionar(self, filas: int, columnas: int) -> None:
        try:
            _redimensionar(self.fd, filas, columnas)
        except OSError:
            pass

    def cerrar(self) -> None:
        """Cierra el cliente, no los procesos: equivale a desatacharse."""
        # Antes de cerrar el fd: un `add_writer` sobre un descriptor ya cerrado
        # deja al bucle vigilando un número que el sistema puede reasignar.
        self._soltar_espera()
        self._pendiente.clear()
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        # 🔴 Se espera de verdad, con una ventana corta. `WNOHANG` a secas
        # preguntaba «¿ya has muerto?» en el mismo instante del `SIGTERM`, y la
        # respuesta era siempre que no: el hijo quedaba como zombi
        # (`[tmux: client] <defunct>`) hasta que el sistema operativo lo
        # recogiera por su cuenta. Medido: 20 pestañas seguidas dejaron 26
        # zombis simultáneos colgando del proceso del hub.
        #
        # Son inofensivos salvo por acumularse, pero un servicio que corre
        # semanas no debería ir dejando hijos sin enterrar. Medio segundo basta
        # para un `tmux attach` que acaba de recibir un SIGTERM; si tardara más,
        # se deja sin bloquear la petición.
        for _ in range(50):
            try:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    return
            except ChildProcessError:
                return
            time.sleep(0.01)


async def bombear(adjunto: Adjunto, enviar) -> None:
    """Lee el PTY y empuja al WebSocket hasta que el attach termine."""
    bucle = asyncio.get_running_loop()
    cola: asyncio.Queue[bytes | None] = asyncio.Queue()

    def al_haber_datos() -> None:
        try:
            datos = os.read(adjunto.fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            datos = b""
        cola.put_nowait(datos or None)

    bucle.add_reader(adjunto.fd, al_haber_datos)
    try:
        while True:
            datos = await cola.get()
            if datos is None:
                return
            await enviar(datos)
    finally:
        try:
            bucle.remove_reader(adjunto.fd)
        except (OSError, ValueError):
            pass
