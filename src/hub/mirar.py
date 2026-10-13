"""Pintar una página en un PNG. Lo que hace comprobable «se ve bien».

Existe por la regla dura 20 —lo que se ve en pantalla se mide en un navegador,
no se razona— y porque hacía falta en tres sitios: el catálogo de muestras, las
pantallas del hub y lo que construye un agente para otra persona.

🔴 **El navegador de Windows NO sirve para comprobar el móvil**, y es el fallo
más caro de los que esconde esto. En WSL el Chrome que hay a mano suele ser el
de Windows, y ése **recorta su ventana a 500 px de ancho como mínimo**: se le
pide 390, maqueta a 500 y captura los primeros 390. El resultado es
indistinguible de un desbordamiento horizontal, así que una pantalla
perfectamente correcta parece rota — y una rota de verdad podría parecer bien.
Medido el 18-sep sobre una página que a 390 px reales cabe entera.

Por eso aquí se prefiere **un Chromium de Linux** cuando lo hay, aunque esté
enterrado en la caché de Playwright, y el de Windows queda como último recurso
con su aviso puesto.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Por debajo de esto, el Chrome de Windows miente: maqueta más ancho y recorta.
ANCHO_MINIMO_DE_WINDOWS = 500

# Donde Playwright deja sus navegadores. No es una dependencia del hub: si está,
# se aprovecha; si no, se sigue con lo que haya en el PATH.
_CACHE_PLAYWRIGHT = Path.home() / ".cache" / "ms-playwright"


def cual() -> str | None:
    """El mejor navegador disponible, en orden de menos mentiras.

    Devuelve `None` si no hay ninguno: nada de esto hace falta para USAR el hub,
    sólo para comprobar cómo se ve algo.
    """
    for nombre in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if hallado := shutil.which(nombre):
            return hallado
    # La caché de Playwright, de la más nueva a la más vieja.
    if _CACHE_PLAYWRIGHT.is_dir():
        candidatos = sorted(_CACHE_PLAYWRIGHT.glob("chromium-*/chrome-linux*/chrome"),
                            reverse=True)
        if candidatos:
            return str(candidatos[0])
    windows = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
    return str(windows) if windows.is_file() else None


def es_de_windows(chrome: str) -> bool:
    return chrome.lower().endswith(".exe")


def para(chrome: str, ruta: Path | str) -> str:
    r"""La misma ruta, dicha como la entiende ESE navegador.

    🔴 El Chrome de Windows no entiende una ruta de Linux: se le pasa y contesta
    que sí **sin escribir nada**. El fallo no se ve —sale con código 0— y el
    síntoma es una captura que no existe. Comprobado que por la ruta UNC
    (`\\wsl.localhost\...`) lee y escribe bien.
    """
    if not es_de_windows(chrome):
        return str(ruta)
    traducida = subprocess.run(["wslpath", "-w", str(ruta)],
                               capture_output=True, text=True, check=False)
    return traducida.stdout.strip() or str(ruta)


class SinNavegador(RuntimeError):
    """No hay con qué mirar. Nunca impide usar el hub: sólo comprobar cómo se ve."""


def captura(fuente: str, destino: Path, ancho: int = 1000, alto: int = 900,
            escala: int = 1, espera_ms: int = 2500,
            chrome: str | None = None) -> Path:
    """Pinta `fuente` —una URL o un archivo— y devuelve dónde quedó el PNG.

    🔴 Avisa, y no en silencio, cuando se pide un ancho que el navegador
    disponible no puede dar. Callarlo es lo que convierte una comprobación en
    una mentira con formato de prueba.
    """
    chrome = chrome or cual()
    if not chrome:
        raise SinNavegador(
            "no hay Chrome ni Chromium para pintar la página. Sólo hace falta "
            "para comprobar cómo se ve; el hub funciona igual sin él."
        )
    if es_de_windows(chrome) and ancho < ANCHO_MINIMO_DE_WINDOWS:
        print(f"[mirar] 🔴 el navegador disponible es el de Windows y NO baja de "
              f"{ANCHO_MINIMO_DE_WINDOWS} px: la captura a {ancho} px maqueta a "
              f"{ANCHO_MINIMO_DE_WINDOWS} y recorta, así que parecerá desbordada "
              f"aunque no lo esté.", flush=True)

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not str(fuente).startswith(("http://", "https://", "file://")):
        fuente = para(chrome, fuente)
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-sandbox",
         f"--window-size={ancho},{alto}",
         f"--force-device-scale-factor={escala}",
         f"--virtual-time-budget={espera_ms}",
         f"--screenshot={para(chrome, destino)}", str(fuente)],
        capture_output=True, timeout=120, check=False,
    )
    if not destino.is_file():
        raise SinNavegador(f"el navegador no produjo la captura de «{fuente}»")
    return destino
