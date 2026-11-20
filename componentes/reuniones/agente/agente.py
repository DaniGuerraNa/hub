"""Agente de reuniones para Windows. Graba cuando el hub se lo pide.

Por qué así:
- Corre en Windows y en TU sesión (tarea programada al iniciar sesión): sólo
  ahí se ve el escritorio y el audio de las aplicaciones. Lanzado desde WSL
  caería en la sesión 0, que no ve ninguna de las dos cosas.
- No escucha en ningún puerto: PREGUNTA al hub cada segundo («¿grabo?»).
  Desde Windows se llega al hub de WSL; al revés, con WSL en NAT, no. Y un
  puerto que no se abre no hay que protegerlo.
- Graba tres cosas por separado:
    reunion.wav  el audio SÓLO de la aplicación elegida (WASAPI process
                 loopback vía proctap): otra música o un vídeo no entran.
    micro.wav    tu micrófono, aparte: así se sabe qué dijiste tú.
    fotos/       el monitor donde está la ventana de la app (o el elegido),
                 a 1 fps, guardando sólo los fotogramas que CAMBIAN (una
                 diapositiva quieta es una foto).
"""
import argparse
import io
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import wave
from pathlib import Path

VERSION = "0.3.0"
HUB = os.environ.get("REUNIONES_HUB", "http://127.0.0.1:8787")
# Las grabaciones y el log van junto a la carpeta del agente (`<base>\agente`
# → `<base>\grabaciones`, `<base>\agente.log`): así el agente funciona donde lo
# pongas, y el hub encuentra las grabaciones sabiendo sólo dónde está él.
AQUI = Path(__file__).resolve().parent
RAIZ = Path(os.environ.get("REUNIONES_RAIZ") or AQUI.parent / "grabaciones")
LOG = Path(os.environ.get("REUNIONES_LOG") or AQUI.parent / "agente.log")
UMBRAL_CAMBIO = float(os.environ.get("REUNIONES_UMBRAL", "4.0"))   # media de |diferencia| en 0-255
ANCHO_MAX = 1600


def log(*a):
    linea = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(linea, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


TOKEN = Path(os.environ.get("REUNIONES_TOKEN_ARCHIVO") or Path(__file__).with_name("token"))


class SinLlave(Exception):
    """El hub no acepta la llave: falta el archivo `token` o es una vieja."""


def llave():
    """La llave con la que el agente demuestra al hub que es él (decisión 280
    del hub). Se lee en CADA llamada: así, al sacar una nueva desde la pantalla
    Reuniones —que la escribe en este archivo— vale al momento, sin reiniciar."""
    if os.environ.get("REUNIONES_TOKEN"):
        return os.environ["REUNIONES_TOKEN"].strip()
    try:
        return TOKEN.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _cabeceras(tipo):
    c = {"Content-Type": tipo}
    if (k := llave()):
        c["X-Reuniones-Token"] = k
    return c


def _post(ruta, datos=None, cuerpo=None, tipo="application/json", timeout=5):
    data = cuerpo if cuerpo is not None else json.dumps(datos or {}).encode()
    req = urllib.request.Request(HUB + ruta, data=data, method="POST", headers=_cabeceras(tipo))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SinLlave() from None
        raise


# ─────────────────────────── qué hay en la máquina ───────────────────────────

def monitores():
    import mss
    with mss.MSS() as s:
        # s.monitors[0] es el escritorio entero; los demás, uno por pantalla.
        return [{"n": i, "izq": m["left"], "arr": m["top"], "ancho": m["width"], "alto": m["height"]}
                for i, m in enumerate(s.monitors) if i > 0]


def miniatura(n: int) -> bytes:
    import mss
    from PIL import Image
    with mss.MSS() as s:
        img = s.grab(s.monitors[n])
    im = Image.frombytes("RGB", img.size, img.rgb)
    im.thumbnail((480, 270))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=70)
    return b.getvalue()


def microfonos():
    import sounddevice as sd
    hostapis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and "WASAPI" in hostapis[d["hostapi"]]["name"]:
            out.append({"n": i, "nombre": d["name"]})
    return out


def apps_con_audio():
    """Aplicaciones con una sesión de audio abierta (las que pueden sonar), y si
    está SONANDO ahora. Teams abre la suya al entrar en una llamada.

    Un mismo nombre tiene muchos procesos (Teams, Spotify, el navegador): el que
    importa es el dueño de la sesión de audio, y de ése se da el pid. Si hay
    varias sesiones, gana la activa."""
    from pycaw.pycaw import AudioUtilities
    vistas = {}
    for s in AudioUtilities.GetAllSessions():
        if not s.Process:
            continue
        try:
            nombre, pid, activa = s.Process.name(), s.Process.pid, s.State == 1
        except Exception:
            continue
        if nombre not in vistas or (activa and not vistas[nombre]["activa"]):
            vistas[nombre] = {"nombre": nombre, "pid": pid, "activa": activa}
    return [vistas[n] for n in sorted(vistas)]


def pid_de(nombre: str) -> int | None:
    for a in apps_con_audio():
        if a["nombre"].lower() == nombre.lower():
            return a["pid"]
    return None


# ─────────────────── en qué monitor está la ventana de la app ───────────────────
# El monitor se repetía de la grabación anterior y, al mover Teams a otra
# pantalla, se grabó semanas la que no era. Ahora se mira dónde está la ventana.
# Medido con Teams en una llamada: dos ventanas visibles del proceso, la de la
# reunión («<asunto> | Microsoft Teams») y la principal («Chat | Microsoft
# Teams»). Y sus ventanas son de OTRO proceso que la sesión de audio: se buscan
# por nombre, no por el pid de la orden.

# Primer tramo del título de la ventana PRINCIPAL de Teams, según la sección
# abierta. Una ventana que no empieza así es la de la reunión.
SECCIONES_PRINCIPAL = {
    "chat", "actividad", "calendario", "teams", "llamadas", "archivos", "onedrive", "aplicaciones",
    "comunidades", "personas", "copilot", "activity", "calendar", "calls", "files", "apps",
    "communities", "people", "microsoft teams",
}
REVISAR_MONITOR_S = 15
MINIMA = (200, 150)        # menos que esto es un aviso o una miniatura, no la reunión


def elegir_ventana(ventanas: list[dict], preferida=None) -> dict | None:
    """La ventana de la reunión entre las de la app (en orden Z, la de arriba primero).

    Se queda con la que ya seguía mientras exista: así no salta de pantalla
    porque alguien abra el chat principal en otra."""
    utiles = [v for v in ventanas if v["ancho"] >= MINIMA[0] and v["alto"] >= MINIMA[1]]
    if not utiles:
        return None
    if preferida is not None:
        for v in utiles:
            if v["hwnd"] == preferida:
                return v
    reunion = [v for v in utiles
               if (v.get("titulo") or "").split("|")[0].strip().lower() not in SECCIONES_PRINCIPAL]
    return (reunion or utiles)[0]


def monitor_de(ventana: dict, monitores: list[dict]) -> int | None:
    """El monitor que más superficie tiene de la ventana (una maximizada asoma
    8 px a los lados, así que no vale mirar una esquina)."""
    mejor, area_mejor = None, 0
    for m in monitores:
        ancho = min(ventana["izq"] + ventana["ancho"], m["izq"] + m["ancho"]) - max(ventana["izq"], m["izq"])
        alto = min(ventana["arr"] + ventana["alto"], m["arr"] + m["alto"]) - max(ventana["arr"], m["arr"])
        area = max(0, ancho) * max(0, alto)
        if area > area_mejor:
            mejor, area_mejor = m["n"], area
    return mejor


def ventanas_de(nombre: str) -> list[dict]:
    """Ventanas visibles, sin minimizar ni ocultas por el sistema, de los
    procesos que se llaman `nombre`, en orden Z. Sólo en Windows.

    Las coordenadas salen en píxeles reales porque mss ya hizo el proceso
    consciente del DPI, igual que las de sus monitores."""
    import ctypes
    from ctypes import wintypes
    u32, k32, dwm = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    # Tipos declarados: sin ellos un HWND o un handle pasan como int de 32 bits.
    H, P = wintypes.HWND, ctypes.POINTER
    for f, args, res in (
            (u32.IsWindowVisible, [H], wintypes.BOOL), (u32.IsIconic, [H], wintypes.BOOL),
            (u32.GetWindowThreadProcessId, [H, P(wintypes.DWORD)], wintypes.DWORD),
            (u32.GetWindowRect, [H, P(wintypes.RECT)], wintypes.BOOL),
            (u32.GetWindowTextW, [H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            (dwm.DwmGetWindowAttribute, [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD], ctypes.c_long),
            (k32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (k32.QueryFullProcessImageNameW, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                              P(wintypes.DWORD)], wintypes.BOOL),
            (k32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL)):
        f.argtypes, f.restype = args, res
    nombre = nombre.lower()
    nombres: dict[int, str] = {}

    def proceso(pid: int) -> str:
        if pid not in nombres:
            nombres[pid] = ""
            h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    tam = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
                        nombres[pid] = buf.value.rsplit("\\", 1)[-1].lower()
                finally:
                    k32.CloseHandle(h)
        return nombres[pid]

    vistas = []
    fallos = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        # Una excepción aquí dentro no sale de EnumWindows: ctypes la tira a
        # stderr, donde nadie la ve, y la lista se queda a medias. Se guarda
        # y se relanza fuera (regla 21 del hub: un fallo no se calla).
        try:
            return _cada(hwnd)
        except Exception as e:
            fallos.append(e)
            return False

    def _cada(hwnd):
        if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if proceso(pid.value) != nombre:
            return True
        oculta = wintypes.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(oculta), 4)     # DWMWA_CLOAKED
        if oculta.value:
            return True
        r = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        titulo = ctypes.create_unicode_buffer(300)
        u32.GetWindowTextW(hwnd, titulo, 300)
        vistas.append({"hwnd": int(hwnd), "titulo": titulo.value, "izq": r.left, "arr": r.top,
                       "ancho": r.right - r.left, "alto": r.bottom - r.top})
        return True

    u32.EnumWindows(cada, 0)
    if fallos:
        raise fallos[0]
    return vistas


# ─────────────────────────────── la grabación ───────────────────────────────

class Grabacion:
    def __init__(self, orden: dict):
        self.id = orden["id"]
        self.dir = RAIZ / self.id
        (self.dir / "fotos").mkdir(parents=True, exist_ok=True)
        self.orden = orden
        self.inicio = time.time()
        self.parar_ = threading.Event()
        self.hilos = []
        self.fotos = 0
        self.errores = []
        self.proc_audio = None
        # El monitor que se graba de verdad y de dónde salió: «ventana» (donde
        # está la de la app), «heredado» (se pidió seguirla y no se encontró:
        # el de la orden) o «elegido» (la orden dice cuál).
        self.monitor = int(orden.get("monitor") or 1)
        self.monitor_origen = "elegido"
        self.cambios_monitor: list[dict] = []
        self.ventana = None
        self._fallo_ventanas = False

    def meta(self, **extra):
        m = {"id": self.id, "inicio": self.inicio, "monitor": self.monitor,
             "monitor_pedido": self.orden.get("monitor"), "monitor_origen": self.monitor_origen,
             "cambios_monitor": self.cambios_monitor,
             "proceso": {"nombre": self.orden.get("app")}, "micro": self.orden.get("micro"),
             "titulo": self.orden.get("titulo", ""), "agente": VERSION, **extra}
        (self.dir / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    def empezar(self):
        self.meta()
        for nombre, f in (("pantalla", self._pantalla), ("micro", self._micro), ("app", self._app)):
            h = threading.Thread(target=self._seguro, args=(nombre, f), daemon=True)
            h.start()
            self.hilos.append(h)
        log("grabando", self.id, self.orden)

    def _seguro(self, nombre, f):
        try:
            f()
        except Exception as e:
            self.errores.append(f"{nombre}: {e}")
            log("ERROR", nombre, traceback.format_exc())

    def _pantalla(self):
        import mss
        import numpy as np
        from PIL import Image
        anterior = None
        seguir = bool(self.orden.get("seguir_app") and self.orden.get("app"))
        with mss.MSS() as s:
            monitores = [{"n": i, "izq": m["left"], "arr": m["top"], "ancho": m["width"], "alto": m["height"]}
                         for i, m in enumerate(s.monitors) if i > 0]
            if self.monitor >= len(s.monitors):
                self.monitor = 1
            if seguir:
                self.monitor_origen = "heredado"
                self._seguir_ventana(monitores, int(time.time() - self.inicio), al_empezar=True)
                if self.monitor_origen == "heredado":
                    log("no encontré la ventana de", self.orden.get("app"), "→ monitor", self.monitor,
                        "de la orden")
                self.cambios_monitor.append({"segundo": 0, "monitor": self.monitor, "origen": self.monitor_origen})
                self.meta()
            mon = s.monitors[self.monitor]
            revisado = time.time()
            while not self.parar_.is_set():
                t0 = time.time()
                if seguir and t0 - revisado >= REVISAR_MONITOR_S:
                    revisado = t0
                    antes = len(self.cambios_monitor)
                    if self._seguir_ventana(monitores, int(t0 - self.inicio)):
                        mon = s.monitors[self.monitor]
                        anterior = None          # pantalla nueva: su primera foto se guarda
                    if len(self.cambios_monitor) != antes:
                        self.meta()              # también si sólo dejó de ser heredado
                img = s.grab(mon)
                im = Image.frombytes("RGB", img.size, img.rgb)
                huella = np.asarray(im.convert("L").resize((96, 54)), dtype=np.int16)
                if anterior is None or np.abs(huella - anterior).mean() > UMBRAL_CAMBIO:
                    anterior = huella
                    if im.width > ANCHO_MAX:
                        im = im.resize((ANCHO_MAX, round(im.height * ANCHO_MAX / im.width)))
                    seg = int(t0 - self.inicio)
                    im.save(self.dir / "fotos" / f"{seg:06d}.jpg", "JPEG", quality=72)
                    self.fotos += 1
                self.parar_.wait(max(0.0, 1.0 - (time.time() - t0)))

    def _seguir_ventana(self, monitores: list[dict], seg: int, al_empezar: bool = False) -> bool:
        """Mira dónde está ahora la ventana de la app. True si hay que cambiar
        de monitor. Si no la encuentra, se queda donde estaba: perder la
        reunión de vista un rato es mejor que saltar a una pantalla cualquiera."""
        try:
            ventanas = ventanas_de(str(self.orden["app"]))
        except Exception as e:      # sin ventanas no se para la grabación: se graba el que había
            if not self._fallo_ventanas:
                self._fallo_ventanas = True
                self.errores.append(f"ventanas: {e}")
                log("ERROR buscando la ventana", traceback.format_exc())
            return False
        v = elegir_ventana(ventanas, self.ventana)
        n = monitor_de(v, monitores) if v else None
        if n is None:
            return False
        self.ventana = v["hwnd"]
        cambia = n != self.monitor
        if cambia or self.monitor_origen != "ventana":
            if not al_empezar:   # la entrada del segundo 0 la pone _pantalla, con su origen
                self.cambios_monitor.append({"segundo": seg, "monitor": n, "origen": "ventana"})
            log(f"la ventana de {self.orden['app']} está en el monitor {n}")
        self.monitor, self.monitor_origen = n, "ventana"
        return cambia

    def _micro(self):
        import sounddevice as sd
        micro = self.orden.get("micro")
        if micro in (None, "", "ninguno"):
            return
        dev = int(micro) if str(micro).isdigit() else None
        info = sd.query_devices(dev, "input")
        tasa = int(info["default_samplerate"])
        with wave.open(str(self.dir / "micro.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tasa)
            cola = queue.Queue()
            with sd.RawInputStream(device=dev, samplerate=tasa, channels=1, dtype="int16",
                                   callback=lambda d, f, t, s: cola.put(bytes(d))):
                while not self.parar_.is_set():
                    try:
                        w.writeframes(cola.get(timeout=0.5))
                    except queue.Empty:
                        pass
                while not cola.empty():
                    w.writeframes(cola.get())

    def _app(self):
        """El audio de la aplicación, con el CLI de proctap (s16le 48 kHz estéreo,
        formato documentado en su README).

        🔴 Windows sólo entrega audio mientras la aplicación SUENA: en silencio
        llegan unos pocos KB. Escrito tal cual, la pista se encoge y sus horas
        dejan de coincidir con el micro y las capturas (medido: 26 KB en 4 s).
        Así que se rellena con silencio según el reloj: la muestra N de la
        pista es siempre el instante inicio + N/48000."""
        nombre = self.orden.get("app")
        if not nombre:
            return
        pid = self.orden.get("pid") or pid_de(nombre)
        exe = Path(sys.executable).with_name("proctap.exe")
        cmd = [str(exe) if exe.exists() else "proctap", "--stdout", "--format", "int16"]
        cmd += ["--pid", str(pid)] if pid else ["--name", nombre]
        self.proc_audio = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        TASA, BPF = 48000, 4                      # bytes por fotograma: 2 canales × 2 bytes
        cola = queue.Queue()

        def leer():
            while True:
                b = self.proc_audio.stdout.read1(65536) if hasattr(self.proc_audio.stdout, "read1") \
                    else self.proc_audio.stdout.read(4096)
                if not b:
                    cola.put(None)
                    return
                cola.put((time.time(), b))
        threading.Thread(target=leer, daemon=True).start()
        escritos = 0
        resto = b""
        with wave.open(str(self.dir / "reunion.wav"), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(TASA)

            def rellenar_hasta(t):
                nonlocal escritos
                faltan = int((t - self.inicio) * TASA) - escritos
                if faltan > 0:
                    w.writeframes(b"\x00" * (faltan * BPF))
                    escritos += faltan
            ultimo = time.time()
            while True:
                try:
                    x = cola.get(timeout=0.2)
                except queue.Empty:
                    if self.parar_.is_set():
                        break
                    # Sólo tras un rato SIN datos, y quedándose 0,5 s por detrás
                    # del reloj: lo que llega lo hace con retraso, y rellenar
                    # hasta «ahora» lo duplicaba (medido: 8 s daban 14,9 s).
                    if time.time() - ultimo > 0.5:
                        rellenar_hasta(time.time() - 0.5)
                    continue
                if x is None:
                    break
                ultimo, b = x
                b = resto + b
                n = len(b) // BPF
                resto = b[n * BPF:]
                w.writeframes(b[:n * BPF])
                escritos += n
            rellenar_hasta(time.time())
        err = self.proc_audio.stderr.read().decode(errors="replace").strip()
        if self.proc_audio.returncode not in (0, None) and not self.parar_.is_set():
            raise RuntimeError(f"proctap terminó ({self.proc_audio.returncode}): {err[-300:]}")

    def parar(self):
        self.parar_.set()
        if self.proc_audio and self.proc_audio.poll() is None:
            self.proc_audio.terminate()
        for h in self.hilos:
            h.join(timeout=10)
        self.meta(fin=time.time(), fotos=self.fotos, errores=self.errores)
        log("parada", self.id, f"{time.time() - self.inicio:.0f} s, {self.fotos} fotos", self.errores or "")

    def estado(self):
        return {"id": self.id, "segundos": int(time.time() - self.inicio), "fotos": self.fotos,
                "errores": self.errores[-3:], "monitor": self.monitor, "monitor_origen": self.monitor_origen}


# ─────────────────────────────── el bucle ───────────────────────────────

def abrir(ruta: str) -> bool:
    """Una pantalla del hub en el navegador de esta PC (la pide el secretario).

    Sólo rutas del hub («/trabajo?slot=3»), pegadas a la dirección del hub que
    conoce el agente: aunque alguien escribiera una URL en la orden, no podría
    mandar el navegador a otra web."""
    if not ruta.startswith("/") or ruta.startswith("//") or "\\" in ruta:
        log("ruta rechazada:", ruta[:120])
        return False
    url = HUB.rstrip("/") + ruta
    if hasattr(os, "startfile"):
        os.startfile(url)
    else:
        import webbrowser
        webbrowser.open(url)
    log("abierta:", ruta[:120])
    return True


def bucle():
    log(f"agente {VERSION} → {HUB}, graba en {RAIZ}")
    grab = None
    inventario, cuando_inv = {}, 0.0
    avisado_llave = 0.0
    abiertas: list[str] = []      # se confirman en el latido siguiente
    while True:
        try:
            if time.time() - cuando_inv > 15:
                inventario = {"monitores": monitores(), "microfonos": microfonos(), "apps": apps_con_audio()}
                cuando_inv = time.time()
            r = _post("/api/reuniones/latido", {"agente": VERSION, "equipo": platform.node(),
                                                "grabando": grab.estado() if grab else None,
                                                "abiertas": abiertas, **inventario})
            abiertas = []
            for p in r.get("abrir") or []:
                try:
                    if abrir(str(p.get("ruta") or "")):
                        abiertas.append(str(p.get("id")))
                except Exception as e:  # una pantalla que no abre no para el agente
                    log("no se pudo abrir:", repr(e)[:200])
            orden = r.get("orden") or {}
            if orden.get("grabar") and not grab:
                grab = Grabacion(orden)
                grab.empezar()
            elif not orden.get("grabar") and grab:
                grab.parar()
                _post("/api/reuniones/latido", {"agente": VERSION, "grabando": None, "terminada": grab.id,
                                                **inventario})
                grab = None
            if r.get("miniaturas"):
                for m in inventario.get("monitores", []):
                    _post(f"/api/reuniones/miniatura/{m['n']}", cuerpo=miniatura(m["n"]), tipo="image/jpeg")
                cuando_inv = 0
        except SinLlave:
            # Una vez por minuto, no por segundo: el log es lo que se mira para
            # saber qué pasa, y mil líneas iguales esconden la única distinta.
            if time.time() - avisado_llave > 60:
                log(f"el hub rechaza la llave ({'no hay' if not llave() else 'no vale'}): "
                    f"en el hub, pantalla Reuniones → «Conectar el agente»; se escribe en {TOKEN}")
                avisado_llave = time.time()
            time.sleep(4)
        except Exception as e:
            log("sin hub o fallo:", repr(e)[:200])
            time.sleep(4)
        time.sleep(1)


def main():
    a = argparse.ArgumentParser(prog="reuniones-agente")
    a.add_argument("que", nargs="?", default="correr", choices=["correr", "inventario", "prueba", "ventana"])
    a.add_argument("--segundos", type=int, default=10)
    a.add_argument("--app")
    a.add_argument("--pid", type=int)
    a.add_argument("--monitor", type=int, default=1)
    a.add_argument("--micro")
    a.add_argument("--seguir", action="store_true", help="grabar donde esté la ventana de --app")
    args = a.parse_args()
    if args.que == "ventana":
        # Qué ventana elegiría y en qué monitor, sin grabar nada.
        import mss
        with mss.MSS():
            vs = ventanas_de(args.app or "ms-teams.exe")
            v = elegir_ventana(vs)
            print(json.dumps({"ventanas": vs, "elegida": v, "monitor": monitor_de(v, monitores()) if v else None},
                             ensure_ascii=False, indent=1))
        return
    if args.que == "inventario":
        print(json.dumps({"monitores": monitores(), "microfonos": microfonos(), "apps": apps_con_audio()},
                         ensure_ascii=False, indent=1))
        return
    if args.que == "prueba":
        g = Grabacion({"id": time.strftime("%Y%m%d-%H%M%S"), "monitor": args.monitor, "app": args.app,
                       "pid": args.pid, "seguir_app": args.seguir,
                       "micro": args.micro, "titulo": "prueba"})
        g.empezar()
        time.sleep(args.segundos)
        g.parar()
        print(json.dumps(g.estado(), ensure_ascii=False))
        return
    bucle()


if __name__ == "__main__":
    main()
