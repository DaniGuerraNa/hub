"""Leer un documento largo de la pantalla del Mac, página a página.

El puente **captura**; quien **transcribe** es Claude (o la persona, que puede
corregir cualquier línea en la pantalla). Separarlo así permite capturar las
cuarenta páginas de un tirón —sin modelo de por medio, con la pantalla
quieta— y transcribirlas después en paralelo.

Cómo se sabe que la copia es buena, sin fiarse de nadie:
- cada línea transcrita lleva su número, el de la columna del editor, y se
  ensambla **por número**: un hueco o una línea leída dos veces se ven solos;
- dos páginas que se solapan y no dicen lo mismo en la misma línea son un
  **conflicto** que alguien resuelve mirando las dos capturas;
- y al final, la **huella** que da la base de datos: si coincide, la copia es
  exacta byte a byte. Si no, no se da por buena por mucho que «se vea bien».

Una lectura vive en `PUENTE_HOME/lecturas/<id>/`: `lectura.json`, las
capturas `p001.png…` y lo transcrito `p001.txt…`.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import huellas
from .config import hogar
from .control import SinControl
from .motor import Motor

MAX_PAGINAS = 400

_LINEA = re.compile(r"^\s*(\d+)\|(.*)$")


@dataclass
class Pagina:
    n: int
    transcrita: bool = False
    quien: str = ""
    primera: int | None = None
    ultima: int | None = None
    errores: list[str] = field(default_factory=list)
    # La pantalla no se quedó quieta antes de capturar: puede estar a medio pintar.
    inestable: bool = False


@dataclass
class Lectura:
    id: str
    nombre: str
    creada: float
    estado: str = "capturando"  # capturando, capturada, cortada, error
    paginas: list[Pagina] = field(default_factory=list)
    error: str = ""
    resoluciones: dict[str, str] = field(default_factory=dict)  # línea → texto elegido
    huella_referencia: str = ""
    variante: dict | None = None
    verificada: bool = False

    # ── disco ───────────────────────────────────────────────────────────────
    @property
    def carpeta(self) -> Path:
        return carpeta_de(self.id)

    def guardar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.carpeta / "lectura.json.tmp"
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1))
        tmp.replace(self.carpeta / "lectura.json")

    def png(self, n: int) -> Path:
        return self.carpeta / f"p{n:03d}.png"

    def txt(self, n: int) -> Path:
        return self.carpeta / f"p{n:03d}.txt"

    def transcripcion(self, n: int) -> str:
        ruta = self.txt(n)
        return ruta.read_text() if ruta.exists() else ""


def carpeta_de(id_: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", id_):
        raise ValueError("identificador de lectura inválido")
    return hogar() / "lecturas" / id_


def cargar(id_: str) -> Lectura:
    datos = json.loads((carpeta_de(id_) / "lectura.json").read_text())
    datos["paginas"] = [Pagina(**p) for p in datos.get("paginas", [])]
    return Lectura(**datos)


def todas() -> list[Lectura]:
    raiz = hogar() / "lecturas"
    if not raiz.exists():
        return []
    salida = []
    for d in raiz.iterdir():
        if (d / "lectura.json").exists():
            try:
                salida.append(cargar(d.name))
            except Exception:  # una lectura rota no tumba la lista
                continue
    return sorted(salida, key=lambda l: l.creada, reverse=True)


def slug(texto: str, largo: int = 40) -> str:
    """«Conciliación año» → «conciliacion-ano»: las tildes fuera, no la letra entera."""
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")[:largo]


def nueva(nombre: str) -> Lectura:
    base = slug(nombre) or "lectura"
    l = Lectura(id=f"{base}-{uuid.uuid4().hex[:6]}", nombre=nombre, creada=time.time())
    l.guardar()
    return l


# ── capturar ────────────────────────────────────────────────────────────────
async def capturar(motor: Motor, lectura: Lectura) -> Lectura:
    """Recorre el documento con Av Pág desde el principio y guarda cada página."""
    p = motor.perfil
    try:
        motor.bitacora.apuntar("lectura", f"empiezo a capturar «{lectura.nombre}»", lectura=lectura.id)
        await motor.aparcar_raton()
        await motor.atajo(p["inicio_documento"])
        lectura.paginas = []

        async def avanzar():
            motor.progreso = f"página {len(lectura.paginas)}"
            await motor.atajo(p["pagina_abajo"], apuntar=False)

        # Una de más: con MAX_PAGINAS justas, la siguiente dice si era el final.
        async for img, quieta in motor.paginas(avanzar, tope=MAX_PAGINAS + 1):
            n = len(lectura.paginas) + 1
            if n > MAX_PAGINAS:
                raise RuntimeError(f"más de {MAX_PAGINAS} páginas: ¿Av Pág no avanza en este programa?")
            img.save(lectura.png(n))
            lectura.paginas.append(Pagina(n=n, inestable=not quieta))
            _avisar_si_inestable(motor, lectura, n, quieta)
            lectura.guardar()
        lectura.estado = "capturada"
        motor.bitacora.apuntar("lectura", f"«{lectura.nombre}»: {len(lectura.paginas)} páginas",
                               lectura=lectura.id)
    except SinControl as e:
        lectura.estado, lectura.error = "cortada", str(e)
        motor.bitacora.apuntar("corte", f"lectura «{lectura.nombre}» cortada", lectura=lectura.id)
    except Exception as e:  # se dice, no se traga
        lectura.estado, lectura.error = "error", f"{type(e).__name__}: {e}"
        motor.bitacora.apuntar("error", lectura.error, lectura=lectura.id)
    lectura.guardar()
    return lectura


def _avisar_si_inestable(motor: Motor, lectura: Lectura, n: int, quieta: bool) -> None:
    if not quieta:
        motor.bitacora.apuntar(
            "aviso", f"«{lectura.nombre}» página {n}: capturada con la pantalla aún moviéndose",
            lectura=lectura.id)


# ── transcribir ─────────────────────────────────────────────────────────────
def analizar(texto: str) -> tuple[list[tuple[int, str]], list[str]]:
    """«N|contenido» por línea → [(N, contenido)], errores.

    El contenido va tal cual tras la primera barra: la sangría es parte del
    código. Los espacios al final se quitan porque en una captura no se ven,
    y lo que no se ve no se puede afirmar.
    """
    lineas: list[tuple[int, str]] = []
    errores: list[str] = []
    for i, cruda in enumerate(texto.replace("\r\n", "\n").split("\n"), 1):
        if not cruda.strip():
            continue
        m = _LINEA.match(cruda)
        if not m:
            errores.append(f"renglón {i} sin «número|»: {cruda[:60]!r}")
            continue
        lineas.append((int(m.group(1)), m.group(2).rstrip()))
    numeros = [n for n, _ in lineas]
    for a, b in zip(numeros, numeros[1:]):
        if b != a + 1:
            errores.append(f"los números saltan de {a} a {b}")
    return lineas, errores


def transcribir(lectura: Lectura, n: int, texto: str, quien: str) -> Pagina:
    pagina = next((p for p in lectura.paginas if p.n == n), None)
    if pagina is None:
        raise ValueError(f"la lectura no tiene página {n}")
    lineas, errores = analizar(texto)
    if not lineas:
        raise ValueError("la transcripción no tiene ninguna línea «número|contenido»")
    lectura.txt(n).write_text("\n".join(f"{k}|{v}" for k, v in lineas) + "\n")
    pagina.transcrita, pagina.quien, pagina.errores = True, quien, errores
    pagina.primera, pagina.ultima = lineas[0][0], lineas[-1][0]
    lectura.verificada = False
    lectura.guardar()
    volcar(lectura)
    return pagina


# ── ensamblar ───────────────────────────────────────────────────────────────
@dataclass
class Ensamblado:
    lineas: list[str]
    conflictos: list[dict]
    huecos: list[tuple[int, int]]
    pendientes: list[int]
    total: int

    @property
    def completo(self) -> bool:
        return not (self.conflictos or self.huecos or self.pendientes) and self.total > 0


def ensamblar(lectura: Lectura) -> Ensamblado:
    vistas: dict[int, dict[str, list[int]]] = {}
    pendientes = []
    for p in lectura.paginas:
        if not p.transcrita:
            pendientes.append(p.n)
            continue
        for k, v in analizar(lectura.transcripcion(p.n))[0]:
            vistas.setdefault(k, {}).setdefault(v, []).append(p.n)
    total = max(vistas) if vistas else 0
    lineas, conflictos, huecos = [], [], []
    hueco_desde = None
    for k in range(1, total + 1):
        versiones = vistas.get(k)
        if not versiones:
            hueco_desde = hueco_desde or k
            lineas.append("")
            continue
        if hueco_desde:
            huecos.append((hueco_desde, k - 1))
            hueco_desde = None
        if str(k) in lectura.resoluciones:
            lineas.append(lectura.resoluciones[str(k)])
        elif len(versiones) == 1:
            lineas.append(next(iter(versiones)))
        else:
            conflictos.append({"linea": k, "versiones": [
                {"texto": t, "paginas": ps} for t, ps in versiones.items()]})
            lineas.append(next(iter(versiones)))
    return Ensamblado(lineas=lineas, conflictos=conflictos, huecos=huecos,
                      pendientes=pendientes, total=total)


def resolver(lectura: Lectura, linea: int, texto: str) -> None:
    lectura.resoluciones[str(linea)] = texto.rstrip()
    lectura.verificada = False
    lectura.guardar()
    volcar(lectura)


def comprobar_huella(lectura: Lectura, referencia: str) -> dict:
    """Compara la copia con la huella de la base y lo deja apuntado."""
    ens = ensamblar(lectura)
    lectura.huella_referencia = huellas.normalizar(referencia)
    variante = huellas.buscar(ens.lineas, referencia) if ens.completo else None
    lectura.variante = variante
    lectura.verificada = variante is not None
    lectura.guardar()
    return {"verificada": lectura.verificada, "completo": ens.completo,
            "variante": huellas.describir(variante) if variante else None}


def texto_ensamblado(lectura: Lectura) -> str:
    return "\n".join(ensamblar(lectura).lineas) + "\n"


def volcar(lectura: Lectura) -> None:
    """La copia de trabajo en un archivo, para que Claude la lea y la edite."""
    (lectura.carpeta / "ensamblado.txt").write_text(texto_ensamblado(lectura))


def resumen(lectura: Lectura) -> dict:
    ens = ensamblar(lectura)
    return {
        "id": lectura.id, "nombre": lectura.nombre, "estado": lectura.estado,
        "error": lectura.error, "paginas": len(lectura.paginas),
        "transcritas": sum(p.transcrita for p in lectura.paginas),
        "lineas": ens.total, "conflictos": len(ens.conflictos), "huecos": ens.huecos,
        "pendientes": ens.pendientes, "completo": ens.completo,
        "verificada": lectura.verificada,
        "variante": huellas.describir(lectura.variante) if lectura.variante else None,
        "errores_por_pagina": {p.n: p.errores for p in lectura.paginas if p.errores},
        # Páginas capturadas sin que la pantalla se quedara quieta: pueden estar a
        # medio pintar, y una transcripción de eso parece buena y no lo es.
        "inestables": [p.n for p in lectura.paginas if p.inestable],
        "archivo": str(lectura.carpeta / "ensamblado.txt"),
    }
