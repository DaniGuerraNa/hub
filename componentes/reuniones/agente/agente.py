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
    fotos/       el monitor elegido a 1 fps, pero guardando sólo los
                 fotogramas que CAMBIAN (una diapositiva quieta es una foto).
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

VERSION = "0.1.0"
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

    def meta(self, **extra):
        m = {"id": self.id, "inicio": self.inicio, "monitor": self.orden.get("monitor"),
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
        n = int(self.orden.get("monitor") or 1)
        anterior = None
        with mss.MSS() as s:
            mon = s.monitors[n]
            while not self.parar_.is_set():
                t0 = time.time()
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
                "errores": self.errores[-3:]}


# ─────────────────────────────── el bucle ───────────────────────────────

def bucle():
    log(f"agente {VERSION} → {HUB}, graba en {RAIZ}")
    grab = None
    inventario, cuando_inv = {}, 0.0
    avisado_llave = 0.0
    while True:
        try:
            if time.time() - cuando_inv > 15:
                inventario = {"monitores": monitores(), "microfonos": microfonos(), "apps": apps_con_audio()}
                cuando_inv = time.time()
            r = _post("/api/reuniones/latido", {"agente": VERSION, "equipo": platform.node(),
                                                "grabando": grab.estado() if grab else None, **inventario})
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
    a.add_argument("que", nargs="?", default="correr", choices=["correr", "inventario", "prueba"])
    a.add_argument("--segundos", type=int, default=10)
    a.add_argument("--app")
    a.add_argument("--pid", type=int)
    a.add_argument("--monitor", type=int, default=1)
    a.add_argument("--micro")
    args = a.parse_args()
    if args.que == "inventario":
        print(json.dumps({"monitores": monitores(), "microfonos": microfonos(), "apps": apps_con_audio()},
                         ensure_ascii=False, indent=1))
        return
    if args.que == "prueba":
        g = Grabacion({"id": time.strftime("%Y%m%d-%H%M%S"), "monitor": args.monitor, "app": args.app,
                       "pid": args.pid,
                       "micro": args.micro, "titulo": "prueba"})
        g.empezar()
        time.sleep(args.segundos)
        g.parar()
        print(json.dumps(g.estado(), ensure_ascii=False))
        return
    bucle()


if __name__ == "__main__":
    main()
