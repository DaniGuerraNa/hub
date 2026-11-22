"""Cuánto de fluido va usar el Mac desde la pantalla del puente (C-0469).

El mismo arnés antes y después de cambiar el directo, para comparar con la misma
vara. Contra el JetKVM falso (H.264 de verdad por WebRTC, como el aparato) con
su marca encendida: arriba a la izquierda de cada fotograma van su número y la
posición del puntero que tiene el Mac (`jetkvm_falso.marcar`). La página, en un
Chromium de Playwright, la lee en cada `requestAnimationFrame` de lo que está
pintando (la imagen MJPEG o el canvas del vídeo), así que se mide lo que se ve:

- **fps pintados**: cuántos números distintos se pintan por segundo, con el
  mando abierto y moviendo el ratón (y, aparte, sólo mirando);
- **retraso del puntero** (p50/p95 de 50 movimientos): del último `mousemove`
  de un movimiento corto (cinco pasos seguidos, como una mano que se para) al
  primer fotograma pintado con el puntero del Mac en ese punto. Si no llega en
  1,5 s, cuenta como perdido: el puntero se quedó en otro sitio;
- **CPU del puente** en 30 s, usando el Mac: el proceso `puente-kvm web` solo
  (el falso corre en este proceso y no cuenta).

La cifra es la del falso en este equipo, no la del aparato: la del aparato se
mide con `/panel?medir=1` (`docs/pruebas-con-el-aparato.md`).

    uv run --frozen python -m tests.medir_directo [--cpu 30] [--json salida.json]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

from puente_kvm.simulador import Simulador

from .jetkvm_falso import MARCA_BLOQUE, MARCA_CAMPOS, JetKVMFalso

# Lo que corre en la página: lee la marca de la superficie que se ve en cada
# cuadro del navegador y apunta cuándo se pintó cada número y cada posición.
LECTOR = """
(() => {
  const B = %(bloque)d, CAMPOS = %(campos)s;
  const N = CAMPOS.reduce((a, c) => a + c[1], 0);
  const lienzo = document.createElement('canvas');
  const ctx = lienzo.getContext('2d', { willReadFrequently: true });
  const m = window.__medir = { vistos: [], posiciones: [], ultimo: null, mov: null };
  function superficie() {
    const v = document.querySelector('#directo-video');
    if (v && !v.hidden && v.width > 0) return v;
    return document.querySelector('#directo');
  }
  function leer() {
    const s = superficie();
    if (!s) return null;
    const ancho = s.tagName === 'CANVAS' ? s.width : s.naturalWidth;
    if (!ancho) return null;
    const escala = ancho / 1920;  // la marca se pinta a 1920 de ancho
    lienzo.width = Math.ceil(N * B * escala); lienzo.height = Math.ceil(2 * B * escala);
    try { ctx.drawImage(s, 0, 0, lienzo.width, lienzo.height, 0, 0, lienzo.width, lienzo.height); }
    catch (e) { return null; }
    const px = ctx.getImageData(0, 0, lienzo.width, lienzo.height).data;
    const luz = (x, y) => { const i = (Math.floor(y) * lienzo.width + Math.floor(x)) * 4; return px[i] + px[i + 1] + px[i + 2]; };
    const valores = {}; let k = 0;
    for (const [campo, bits] of CAMPOS) {
      let v = 0;
      for (let b = 0; b < bits; b++, k++) {
        const cx = (k + 0.5) * B * escala;
        const arriba = luz(cx, 0.5 * B * escala) > 382, abajo = luz(cx, 1.5 * B * escala) > 382;
        if (arriba === abajo) return null;  // mal leída: las dos filas son complementarias
        v = (v << 1) | (arriba ? 1 : 0);
      }
      valores[campo] = v;
    }
    return valores;
  }
  function cuadro(t) {
    const v = leer();
    if (v) {
      const ahora = performance.now();
      if (!m.ultimo || m.ultimo.n !== v.n) m.vistos.push([ahora, v.n]);
      if (!m.ultimo || m.ultimo.x !== v.x || m.ultimo.y !== v.y) m.posiciones.push([ahora, v.x, v.y]);
      m.ultimo = v;
    }
    requestAnimationFrame(cuadro);
  }
  requestAnimationFrame(cuadro);
  // El último mousemove sobre la superficie, con el punto del Mac que le toca
  // (la misma cuenta que punto() en app.js).
  window.addEventListener('mousemove', (e) => {
    const s = superficie(), p = document.querySelector('#pantalla');
    if (!s || !p) return;
    const r = s.getBoundingClientRect();
    m.mov = { t: performance.now(), x: Math.round((e.clientX - r.left) / r.width * (Number(p.dataset.ancho) || 1920)),
              y: Math.round((e.clientY - r.top) / r.height * (Number(p.dataset.alto) || 1080)) };
  }, true);
})();
"""


def _cpu(pid: int) -> float:
    """Segundos de CPU (usuario + sistema) del proceso y sus hilos."""
    campos = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(campos[11]) + int(campos[12])) / os.sysconf("SC_CLK_TCK")


class Falso:
    """El JetKVM falso en su propio hilo y su propio bucle."""

    def __init__(self, **variantes):
        self.sim = Simulador(lineas=[f"-- línea {i}" for i in range(200)])
        self.falso = JetKVMFalso(self.sim)
        self.falso.marcar = True
        for k, v in variantes.items():
            setattr(self.falso, k, v)
        self.bucle = asyncio.new_event_loop()
        threading.Thread(target=self.bucle.run_forever, daemon=True).start()
        self.url = asyncio.run_coroutine_threadsafe(self.falso.arrancar(), self.bucle).result(30)

    def parar(self):
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(self.falso.parar(), self.bucle).result(10)
        self.bucle.call_soon_threadsafe(self.bucle.stop)


POR_OMISION = Path.home() / ".local/share/puente-kvm"


def datos_de_verdad(entorno) -> None:
    """🔴 Aborta si los datos del puente serían los de verdad: un arnés que escribe
    en la bitácora de quien lo usa la ensucia (22-nov, un guion a mano sin
    `PUENTE_HOME`). Sin fijar, el puente usa los de por omisión."""
    hogar = entorno.get("PUENTE_HOME")
    if not hogar or Path(hogar).expanduser().resolve() == POR_OMISION.resolve():
        raise SystemExit("PUENTE_HOME sin fijar o el de por omisión: no mido contra los datos de verdad")


@contextlib.contextmanager
def puente_contra(url: str, carpeta: Path):
    """`puente-kvm web` de verdad, en otro proceso, con sus datos aparte y un puerto libre."""
    from .conftest import puerto_libre

    puerto = puerto_libre()
    entorno = {**os.environ, "PUENTE_HOME": str(carpeta / "puente"), "PUENTE_PUERTO": str(puerto),
               "PUENTE_ENTORNO": str(carpeta / "entorno"), "PUENTE_TMUX_SOCKET": f"puente-medir-{puerto}",
               "PUENTE_TERMINAL_ORDEN": "exec bash --norc --noprofile", "JETKVM_CLAVE": "secreta",
               "CLAUDE_CONFIG_DIR": str(carpeta / "claude")}
    # Como conftest: sin ellas, el puente de la medición se creería el de la unidad de systemd.
    entorno.pop("INVOCATION_ID", None)
    entorno.pop("PUENTE_SERVICIO", None)
    datos_de_verdad(entorno)
    (carpeta / "puente").mkdir(parents=True, exist_ok=True)
    (carpeta / "puente" / "ajustes.json").write_text(json.dumps(
        {"dispositivo": {"tipo": "jetkvm", "url": url, "clave_env": "JETKVM_CLAVE"}}))
    proc = subprocess.Popen([sys.executable, "-m", "puente_kvm", "web"], env=entorno,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{puerto}"
    try:
        fin = time.time() + 60
        while time.time() < fin:
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(base + "/api/estado", timeout=2).json()["dispositivo"].get("conectado"):
                    break
            time.sleep(0.2)
        else:
            raise RuntimeError("el puente no llegó a conectar con el falso")
        yield base, proc.pid
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.run(["tmux", "-L", f"puente-medir-{puerto}", "kill-server"], capture_output=True)


def percentil(datos: list[float], p: float) -> float:
    datos = sorted(datos)
    return datos[min(len(datos) - 1, max(0, round(p / 100 * (len(datos) - 1))))]


def fps_en(pagina, segundos: float, mover=None) -> float:
    """Números distintos pintados por segundo durante `segundos`."""
    t0 = pagina.evaluate("performance.now()")
    fin = time.time() + segundos
    while time.time() < fin:
        if mover:
            mover()
        pagina.wait_for_timeout(200)
    t1 = pagina.evaluate("performance.now()")
    vistos = pagina.evaluate(f"window.__medir.vistos.filter(([t]) => t >= {t0} && t <= {t1}).length")
    return vistos / ((t1 - t0) / 1000)


def medir(cpu_s: float = 30, movimientos: int = 50, **variantes) -> dict:
    resultado: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        # También este proceso, con sus datos aparte: el falso y el simulador corren aquí.
        os.environ.update({"PUENTE_HOME": str(Path(tmp) / "aqui"), "PUENTE_ENTORNO": str(Path(tmp) / "entorno")})
        datos_de_verdad(os.environ)
        falso = Falso(**variantes)
        try:
            resultado = _medir(falso, Path(tmp), cpu_s, movimientos)
        finally:
            falso.parar()
    return resultado


def _medir(falso: Falso, tmp: Path, cpu_s: float, movimientos: int) -> dict:
    from playwright.sync_api import sync_playwright

    resultado: dict = {}
    with puente_contra(falso.url, tmp) as (base, pid), sync_playwright() as pw:
        nav = pw.chromium.launch()
        pagina = nav.new_page(viewport={"width": 1280, "height": 860})
        pagina.add_init_script(LECTOR % {"bloque": MARCA_BLOQUE, "campos": json.dumps(MARCA_CAMPOS)})
        pagina.goto(base + "/panel")
        pagina.wait_for_function("window.__medir && window.__medir.ultimo", timeout=20000)
        pagina.wait_for_timeout(1500)  # que se asiente (y, si lo hay, que el vídeo pase al canvas)
        resultado["superficie"] = pagina.evaluate(
            "(() => { const v = document.querySelector('#directo-video');"
            " return v && !v.hidden && v.width > 0 ? 'canvas' : 'img'; })()")

        resultado["fps_mirando"] = round(fps_en(pagina, 5), 1)
        pagina.click("#mando-usar")
        caja = pagina.locator("#directo-video:not([hidden])").first if resultado["superficie"] == "canvas" \
            else pagina.locator("#directo")
        r = caja.bounding_box()
        azar = random.Random(469)
        dentro = lambda: (r["x"] + azar.uniform(0.15, 0.95) * r["width"],  # noqa: E731
                          r["y"] + azar.uniform(0.1, 0.9) * r["height"])
        pagina.mouse.click(*dentro())

        def menear():
            pagina.mouse.move(*dentro(), steps=3)

        resultado["fps_usando"] = round(fps_en(pagina, 10, menear), 1)

        retrasos, perdidos = [], 0
        for _ in range(movimientos):
            pagina.wait_for_timeout(azar.uniform(150, 350))
            pagina.mouse.move(*dentro(), steps=5)
            mov = pagina.evaluate("window.__medir.mov")
            # El primer cuadro pintado, después del mousemove, con el puntero ahí.
            buscar = ("(m) => { const p = window.__medir.posiciones.find(([t, x, y]) => t >= m.t"
                      " && Math.abs(x - m.x) <= 1 && Math.abs(y - m.y) <= 1); return p ? p[0] : null; }")
            fin = time.time() + 1.5
            llego = None
            while time.time() < fin:
                llego = pagina.evaluate(buscar, mov)
                if llego is not None:
                    break
                pagina.wait_for_timeout(10)
            if llego is None:
                perdidos += 1
            else:
                retrasos.append(llego - mov["t"])
        resultado["retraso_p50_ms"] = round(percentil(retrasos, 50)) if retrasos else None
        resultado["retraso_p95_ms"] = round(percentil(retrasos, 95)) if retrasos else None
        resultado["perdidos"] = f"{perdidos}/{movimientos}"

        antes, t0 = _cpu(pid), time.time()
        fin = t0 + cpu_s
        while time.time() < fin:
            menear()
            pagina.wait_for_timeout(200)
        resultado["cpu_puente_pct"] = round(100 * (_cpu(pid) - antes) / (time.time() - t0), 1)
        nav.close()
    return resultado


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--cpu", type=float, default=30, help="segundos para medir la CPU del puente")
    a.add_argument("--movimientos", type=int, default=50)
    a.add_argument("--perfil", default="high", choices=["high", "baseline"])
    a.add_argument("--gop", type=int, default=15)
    a.add_argument("--sps-solo-al-principio", action="store_true")
    a.add_argument("--json", help="además, guarda el resultado en este archivo")
    o = a.parse_args()
    r = medir(o.cpu, o.movimientos, perfil=o.perfil, gop=o.gop, sps_solo_al_principio=o.sps_solo_al_principio)
    texto = json.dumps(r, ensure_ascii=False, indent=2)
    print(texto)
    if o.json:
        Path(o.json).write_text(texto + "\n")


if __name__ == "__main__":
    main()
