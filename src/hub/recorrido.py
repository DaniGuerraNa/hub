"""Recorrer todas las pantallas del hub en un navegador de verdad (C-0168, decisión 361).

Existe porque los fallos que más han dolido aquí tenían la suite entera en
verde: el 500 de `/trabajo` sin servidor de tmux, el «Cargando…» eterno del
asistente, un script que revienta al arrancar con la página servida perfecta
(regla dura 11) y desbordes a 390 px que sólo aparecían con datos reales. Un
HTTP 200 no dice nada de eso; un navegador sí (regla dura 20).

Cada pantalla se abre a dos anchos —un móvil y un PC— y cuenta como rota si
pasa cualquiera de estas cosas mientras carga:

- un error de JavaScript (`pageerror`) o un `console.error`;
- una respuesta ≥ 400 o una petición fallida: el documento, sus recursos y
  lo que la página pide por `fetch` al arrancar;
- algo que se sale de lado (`scrollWidth` mayor que el ancho pedido);
- una petición a otro origen: el hub no usa CDN (`CLAUDE.md`), y así lo vigila
  una máquina y no la memoria de nadie.

🔴 **Sólo mira, y eso no es negociable contra el hub de alguien.** Toda
petición que no sea GET se corta antes de salir —y se apunta: una pantalla que
escribe al cargar es un hallazgo en sí—, y los WebSocket se simulan sin llegar
al servidor: el de `/trabajo` haría `tmux attach` a una sesión de verdad y la
redimensionaría al ancho del móvil. Las rutas GET que no se visitan están en
`NO_SE_VISITAN`, cada una con su porqué.

Las pantallas salen de las rutas de la propia app (`web.app.routes`), no de
una lista a mano que se queda vieja. Las de detalle (`/proyecto/{id}`…) se
visitan con un id **real**, sacado de los enlaces de las pantallas ya abiertas
y de lo que piden al cargar; un id aprendido para un nombre (`proyecto_id`)
sirve para todas las rutas que lo llevan. Si no aparece ninguno, la ruta va a
`sin_visitar` en vez de inventarse un id que daría un 404 falso — y quien
llama decide si eso es aceptable (el test de la suite no lo acepta).

Playwright no es dependencia del hub (grupo `navegador` de `pyproject.toml`) y
el navegador lo elige `mirar.cual_linux`. Desde la línea de órdenes:

    uv run --group navegador python -m hub.recorrido --url http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote, urlsplit

from . import mirar

ANCHOS = (390, 1200)

# Lo que mide un móvil de verdad de alto: el ancho es lo que se comprueba,
# pero un alto de PC a 390 de ancho no es ningún aparato real.
_ALTOS = {390: 844}

#: Rutas GET que no se visitan, con su porqué. Una ruta nueva entra sola en el
#: recorrido; para dejarla fuera hay que escribir aquí la razón.
NO_SE_VISITAN = {
    "/acceso/alta/{codigo}": "canjea un código de alta: abrirla ya es usarlo",
    "/terminal": "sólo redirige a /trabajo, que ya se visita",
    "/api/sesiones": "lee todos los transcripts de Claude Code: segundos de disco, y no es una pantalla",
}

#: Rutas sin parámetros en el camino que sólo enseñan algo con su consulta.
#: Sin un enlace que la traiga no se visitan: abrirlas peladas da el 404 o la
#: redirección que ya dan a propósito.
PIDEN_CONSULTA = {
    "/navegante/imagen": "sin `flujo`, `cuando` y `nombre` contesta 404 a propósito",
    "/navegante/corrida": "sin `flujo` y `cuando` vuelve a /navegante",
}

#: Rutas cuyo único parámetro no se toma prestado de otra ruta que se llame
#: igual: sólo valen los enlaces que llevan a ellas. Sin esto, el `nombre` de
#: un `/intercambio/bajar/…` cualquiera (un .json) acababa en el visor, que
#: sólo enseña imágenes y contesta 415 a propósito: un fallo del recorrido,
#: no de la pantalla (medido en el hub real el 2026-11-06).
SIN_PRESTAR = {
    "/intercambio/ver/{nombre:path}": "sólo enseña imágenes; un nombre de otra ruta puede no serlo",
}

# Cuánto se espera a que la página deje de pedir cosas después del `load`.
_QUIETO_MS = 400
_ESPERA_MAXIMA_MS = 5000

_DE_LADO = """(ancho) => {
  const doc = document.documentElement;
  const total = Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0);
  if (total <= ancho) return {total, culpables: []};
  // Quién empuja: lo que se sale por su caja o por su contenido —un texto sin
  // espacios no tiene caja propia: asoma en el `scrollWidth` de quien lo lleva—.
  // Lo fijo no empuja la página (se mide contra la ventana, y en el móvil crece
  // con ella: parecería culpable sin serlo), ni lo que está dentro de algo con
  // su propio scroll. De lo que queda, las hojas: el contenido, no cada caja
  // que lo envuelve.
  const aparte = (el) => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.position === 'fixed' || (p !== el && cs.overflowX !== 'visible')) return true;
    }
    return false;
  };
  const derecha = (el) => {
    const r = el.getBoundingClientRect();
    if (!r.width) return 0;
    const propio = getComputedStyle(el).overflowX === 'visible' ? r.left + el.scrollWidth : 0;
    return Math.max(r.right, propio);
  };
  const fuera = [...document.body.querySelectorAll('*')]
    .filter(el => derecha(el) > ancho + 1 && !aparte(el));
  const hojas = fuera.filter(el => !fuera.some(o => o !== el && el.contains(o)));
  const nombre = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className.trim()
       ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  return {total, culpables: hojas.slice(0, 3).map(el =>
    nombre(el) + ' «' + (el.textContent || '').trim().slice(0, 40) + '» → ' +
    Math.round(derecha(el)) + ' px')};
}"""


@dataclass
class Fallo:
    """Una cosa rota, dicha para poder ir a mirarla."""

    ruta: str
    ancho: int | None
    clase: str  # js | consola | http | peticion | desborde | escribe | fuera
    detalle: str

    def __str__(self) -> str:
        donde = f"{self.ruta} @{self.ancho}" if self.ancho else self.ruta
        return f"[{self.clase}] {donde}: {self.detalle}"


@dataclass
class Informe:
    base: str
    visitadas: list[str] = field(default_factory=list)
    comprobadas: list[str] = field(default_factory=list)
    sin_visitar: list[str] = field(default_factory=list)
    fallos: list[Fallo] = field(default_factory=list)

    def texto(self) -> str:
        lineas = [f"Recorrido de {self.base}: {len(self.visitadas)} pantallas en el "
                  f"navegador y {len(self.comprobadas)} respuestas más comprobadas por GET."]
        if self.sin_visitar:
            lineas.append("Sin un id real que seguir (no se visitaron): "
                          + ", ".join(self.sin_visitar))
        if not self.fallos:
            lineas.append("Sin fallos.")
        else:
            lineas.append(f"{len(self.fallos)} fallos:")
            lineas += [f"  {f}" for f in self.fallos]
        return "\n".join(lineas)


def rutas_get(app=None) -> list[str]:
    """Las rutas GET de la app, tal como se declaran (`/proyecto/{proyecto_id}`).

    Fuera las que FastAPI añade por su cuenta (`include_in_schema=False`): hoy
    sólo `/openapi.json`, que es el esquema y no una pantalla (la documentación,
    que cargaba de un CDN, ya no se sirve: C-0178).
    """
    if app is None:
        from .web import app  # importarla no arranca nada: el `lifespan` es al servir
    rutas = []
    for r in app.routes:
        metodos = getattr(r, "methods", None) or set()
        camino = getattr(r, "path", "")
        if ("GET" not in metodos or camino.startswith("/static")
                or not getattr(r, "include_in_schema", True)):
            continue
        if camino not in rutas:
            rutas.append(camino)
    return rutas


def patron(ruta: str) -> re.Pattern:
    """`/reuniones/{id_}/foto/{segundo}` → la expresión, con un grupo por parámetro."""
    def trozo(p: str) -> str:
        if not p.startswith("{"):
            return re.escape(p)
        nombre, _, tipo = p[1:-1].partition(":")
        return f"(?P<{nombre}>{'.+' if tipo == 'path' else '[^/]+'})"
    return re.compile("^" + "".join(trozo(p) for p in re.split(r"(\{[^}]+\})", ruta)) + "$")


def _parametros(ruta: str) -> list[str]:
    return [p.split(":")[0] for p in re.findall(r"\{([^}]+)\}", ruta)]


def _rellenar(ruta: str, valores: dict[str, str]) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: quote(valores[m.group(1).split(":")[0]], safe=""), ruta)


def _es_html(tipo: str) -> bool:
    return tipo.split(";")[0].strip().lower() == "text/html"


def _corta(url: str, base: str) -> str:
    return url[len(base):] if url.startswith(base) else url


class _Visita:
    """Lo que pasa mientras carga UNA página a UN ancho."""

    def __init__(self, base: str, ruta: str, ancho: int, informe: Informe):
        self.base, self.ruta, self.ancho, self.informe = base, ruta, ancho, informe
        self.en_vuelo: set = set()
        self.ultimo = time.monotonic()
        self.pedidas: list[str] = []
        self.escrituras = 0
        # Al cerrar la página se cortan los sondeos que estuvieran en vuelo:
        # eso lo provoca el recorrido, no la pantalla.
        self.cerrada = False

    def fallo(self, clase: str, detalle: str):
        if not self.cerrada:
            self.informe.fallos.append(Fallo(self.ruta, self.ancho, clase, detalle))

    def atar(self, pagina):
        pagina.on("pageerror", lambda e: self._error("js", str(e)))
        pagina.on("console", self._consola)
        pagina.on("request", self._sale)
        pagina.on("requestfinished", self._vuelve)
        pagina.on("requestfailed", self._falla)
        pagina.on("response", self._respuesta)

    def _error(self, clase: str, texto: str):
        texto = (texto.splitlines() or [""])[0][:300]
        # Lo que se queja después de cortar una escritura es, casi seguro, la
        # escritura cortada. Se apunta igual —podría no serlo—, pero dicho, para
        # que se lea como su consecuencia y no como un segundo fallo suelto.
        if self.escrituras:
            texto = "tras cortar una escritura: " + texto
        self.fallo(clase, texto)

    def _consola(self, mensaje):
        # El navegador repite en consola cada respuesta ≥ 400 («Failed to load
        # resource…»): ya cuenta como `http`, con su URL.
        if mensaje.type == "error" and not mensaje.text.startswith("Failed to load resource"):
            self._error("consola", mensaje.text)

    def _sale(self, peticion):
        self.en_vuelo.add(peticion)
        self.ultimo = time.monotonic()
        self.pedidas.append(peticion.url)

    def _vuelve(self, peticion):
        self.en_vuelo.discard(peticion)
        self.ultimo = time.monotonic()

    def _falla(self, peticion):
        self._vuelve(peticion)
        motivo = peticion.failure or ""
        # Las cortadas a propósito ya se apuntaron con su clase al cortarlas.
        if "ERR_BLOCKED_BY_CLIENT" not in motivo:
            self.fallo("peticion", f"{peticion.method} {_corta(peticion.url, self.base)}: {motivo}")

    def _respuesta(self, respuesta):
        if respuesta.status >= 400:
            self.fallo("http", f"{respuesta.status} {respuesta.request.method} "
                               f"{_corta(respuesta.url, self.base)}")

    def esperar_quieta(self, pagina):
        """Hasta que lleve un rato sin pedir nada. Las pantallas que sondean
        cada pocos segundos nunca llegan a `networkidle`, así que no vale."""
        limite = time.monotonic() + _ESPERA_MAXIMA_MS / 1000
        while time.monotonic() < limite:
            pagina.wait_for_timeout(100)
            if not self.en_vuelo and time.monotonic() - self.ultimo >= _QUIETO_MS / 1000:
                return


def recorrer(base: str, anchos=ANCHOS, chrome: str | None = None,
             rutas: list[str] | None = None) -> Informe:
    """Abre cada pantalla del hub de `base` a cada ancho y devuelve lo que falló.

    Lanza `mirar.SinNavegador` si no hay un Chromium de Linux, y
    `ModuleNotFoundError` si falta Playwright.
    """
    chrome = chrome or mirar.cual_linux()
    if not chrome:
        raise mirar.SinNavegador(
            "hace falta un Chromium de Linux (p.ej. el de Playwright): el de Windows "
            f"no baja de {mirar.ANCHO_MINIMO_DE_WINDOWS} px y el móvil saldría mal medido")
    from playwright.sync_api import sync_playwright
    base = base.rstrip("/")
    informe = Informe(base)
    rutas = [r for r in (rutas if rutas is not None else rutas_get()) if r not in NO_SE_VISITAN]

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(executable_path=chrome, headless=True,
                                       args=["--no-sandbox", "--disable-gpu"])
        try:
            _Recorrido(navegador, base, anchos, informe).todo(rutas)
        finally:
            navegador.close()
    return informe


class _Recorrido:
    def __init__(self, navegador, base: str, anchos, informe: Informe):
        self.base, self.informe = base, informe
        origen = urlsplit(base).netloc
        self.contextos = {a: _contexto(navegador, a, origen) for a in anchos}
        self.pedir = next(iter(self.contextos.values()))[0].request
        # Para aprender ids sirven todas las rutas, no sólo las que se recorren.
        self.patrones = [patron(r) for r in rutas_get() if _parametros(r)]
        self.enlaces: list[str] = []
        self.valores: dict[str, str] = {}
        self.hechas: set[str] = set()

    def todo(self, rutas: list[str]):
        llanas = [r for r in rutas if not _parametros(r)]
        # Primero lo que no necesita id: de ahí salen los enlaces a lo demás.
        for ruta in llanas:
            if ruta not in PIDEN_CONSULTA:
                self.visitar(ruta)
        # Y una variante con consulta de cada una que la tenga (`/trabajo?slot=…`,
        # `/navegante/corrida?flujo=…`), que suele ser el detalle —lo que se rompe
        # con datos de verdad—, y las de detalle con un id real. Varias vueltas:
        # lo que enseña una (`/proyecto/demo`, la imagen de una corrida) abre
        # rutas de la siguiente (`/api/estado/demo`, `/navegante/imagen?…`).
        pendientes = [r for r in rutas if r in PIDEN_CONSULTA or _parametros(r)]
        variantes = list(llanas)
        for _ in range(3):
            variantes = [r for r in variantes if not self._variante(r)]
            pendientes = [r for r in pendientes if not (
                self._detalle(r) if _parametros(r) else r not in variantes)]
        self.informe.sin_visitar += pendientes

    def _variante(self, ruta: str) -> bool:
        otra = next((e for e in self.enlaces if "?" in e and e.split("?")[0] == ruta
                     and "aviso=" not in e), None)
        if otra:
            self.visitar(otra)
        return otra is not None

    def _detalle(self, ruta: str) -> bool:
        casa = patron(ruta)
        hallado = next((e for e in self.enlaces if casa.match(e.split("?")[0])), None)
        # Un id suelto sí se reutiliza; dos aprendidos por separado podrían no
        # ir juntos (el lienzo de otro proyecto) y darían un 404 que no es fallo.
        params = _parametros(ruta)
        if (hallado is None and len(params) == 1 and params[0] in self.valores
                and ruta not in SIN_PRESTAR):
            hallado = _rellenar(ruta, self.valores)
        if hallado is None:
            return False
        self.visitar(hallado)
        return True

    def _aprender(self, urls: list[str]):
        """Los enlaces, y el valor de cada parámetro por su nombre: el de la
        consulta (`?slot=3`) y el del camino (`/proyecto/demo` → `proyecto_id`)."""
        for url in urls:
            if url in self.enlaces:
                continue
            self.enlaces.append(url)
            camino, _, consulta = url.partition("?")
            for nombre, valor in parse_qsl(consulta):
                self.valores.setdefault(nombre, valor)
            for p in self.patrones:
                if m := p.match(camino):
                    for nombre, valor in m.groupdict().items():
                        self.valores.setdefault(nombre, valor)

    def visitar(self, url: str):
        if url in self.hechas:
            return
        self.hechas.add(url)
        try:
            r = self.pedir.get(self.base + url, max_redirects=0, timeout=30_000)
        except Exception as exc:  # noqa: BLE001 — una ruta rota no para el recorrido
            self.informe.fallos.append(Fallo(url, None, "peticion", str(exc).splitlines()[0]))
            return
        if r.status >= 400:
            self.informe.fallos.append(Fallo(url, None, "http", f"{r.status} GET {url}"))
            return
        if 300 <= r.status < 400 or not _es_html(r.headers.get("content-type", "")):
            self.informe.comprobadas.append(url)
            return
        self.informe.visitadas.append(url)
        for ancho, (contexto, estado) in self.contextos.items():
            self._aprender(_abrir(contexto, estado, self.base, url, ancho, self.informe))


def _contexto(navegador, ancho: int, origen: str):
    movil = ancho < 700
    contexto = navegador.new_context(
        viewport={"width": ancho, "height": _ALTOS.get(ancho, 900)},
        is_mobile=movil, has_touch=movil, locale="es-ES",
    )
    # Las páginas de un contexto se abren de una en una: la visita en curso es
    # a quien se le apunta lo que corte el filtro.
    estado = {"visita": None}

    def filtrar(route, request):
        visita = estado.get("visita")
        destino = urlsplit(request.url)
        if destino.scheme in ("http", "https") and destino.netloc != origen:
            if visita:
                visita.fallo("fuera", f"pide a otro origen: {request.url[:200]}")
            return route.abort("blockedbyclient")
        if request.method not in ("GET", "HEAD"):
            if visita:
                visita.escrituras += 1
                visita.fallo("escribe", f"la pantalla escribe al cargar: {request.method} "
                                        f"{_corta(request.url, visita.base)} (cortado)")
            return route.abort("blockedbyclient")
        return route.continue_()

    contexto.route("**/*", filtrar)
    # Sin `connect_to_server`, el socket se queda en el navegador: abre y calla.
    # La terminal se ve «conectada» y no hay ningún `tmux attach` (regla 15).
    contexto.route_web_socket(re.compile(".*"), lambda ws: None)
    return contexto, estado


def _abrir(contexto, estado: dict, base: str, url: str, ancho: int,
           informe: Informe) -> list[str]:
    """Abre `url` a `ancho`, apunta lo que falle y devuelve sus enlaces del hub."""
    visita = _Visita(base, url, ancho, informe)
    estado["visita"] = visita
    pagina = contexto.new_page()
    try:
        visita.atar(pagina)
        try:
            pagina.goto(base + url, wait_until="load", timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            visita.fallo("peticion", f"no cargó: {str(exc).splitlines()[0]}")
            return []
        visita.esperar_quieta(pagina)
        lado = pagina.evaluate(_DE_LADO, ancho)
        if lado["total"] > ancho:
            visita.fallo("desborde", f"{lado['total']} px de ancho en {ancho}: "
                                     + ("; ".join(lado["culpables"]) or "sin culpable a la vista"))
        # Las imágenes también, aunque no se hayan pedido: las de `loading="lazy"`
        # dentro de un `<details>` cerrado sólo se piden al abrirlo.
        hrefs = pagina.eval_on_selector_all(
            "a[href], img[src]", "els => els.map(e => e.href || e.src)")
        # Lo que la página pidió al cargar también enseña ids reales: así se
        # llega a `/api/sesion/{s}/ventanas` o `/api/lienzo/{p}/{l}`.
        hrefs += visita.pedidas
    finally:
        visita.cerrada = True
        estado["visita"] = None
        pagina.close()
    propios = []
    for h in hrefs:
        if h.startswith(base + "/"):
            resto = h[len(base):].split("#")[0]
            if resto and not resto.startswith("/static/") and resto not in propios:
                propios.append(resto)
    return propios


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m hub.recorrido",
        description="Abre todas las pantallas del hub en Chromium a 390 y 1200 px "
                    "y dice cuáles fallan. Sólo mira: corta toda escritura.")
    p.add_argument("--url", default="http://127.0.0.1:8787")
    p.add_argument("--anchos", default=",".join(map(str, ANCHOS)),
                   help="anchos en px, separados por comas")
    p.add_argument("--ruta", action="append",
                   help="recorrer sólo esta ruta (se puede repetir)")
    a = p.parse_args(argv)
    try:
        informe = recorrer(a.url, tuple(int(x) for x in a.anchos.split(",")), rutas=a.ruta)
    except ModuleNotFoundError:
        print("Falta Playwright. Lánzalo así:\n"
              "  uv run --group navegador python -m hub.recorrido", file=sys.stderr)
        return 2
    except mirar.SinNavegador as exc:
        print(f"No se puede recorrer: {exc}", file=sys.stderr)
        return 2
    print(informe.texto())
    return 1 if informe.fallos else 0


if __name__ == "__main__":
    sys.exit(main())
