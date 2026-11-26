"""Mediciones de uso sin contenido: cuánto tarda cada cosa y cuántas veces pasa (C-0483).

Para qué: decidir con cifras del aparato de verdad (el JetKVM y el Mac de quien
lo usa) cuánto sobra o falta en cada espera, qué herramienta cuesta más y por
qué vuelve el control. Quien escribe el código no tiene el aparato; quien lo
usa, sí. Así que el puente apunta, y ella lo manda cuando quiera.

🔴 Lo que se apunta es una **lista cerrada** (`ESQUEMA`): por tipo de línea,
qué claves hay y de qué clase es cada valor —un número, un sí/no, una palabra
de una lista cerrada o un número de versión—. Nada de texto: ni lo tecleado,
ni lo que se lee, ni nombres de lecturas, de cambios o de objetos, ni rutas, ni
coordenadas, ni la pantalla. Por eso no es la bitácora, que lleva contenido a
propósito y sólo se comparte tapada por patrones: un filtro de patrones es una
red, no una garantía; una lista cerrada no deja pasar lo que no está en ella.
Y se vuelve a comprobar cada línea al empaquetar: una que alguien haya tocado a
mano y no case con la lista no entra en el .zip.

- Vive en `PUENTE_HOME/mediciones/AAAA-MM-DD.jsonl`, un archivo por día; los
  de más de 30 días se borran al arrancar (`podar`). No sale nada solo: el
  .zip lo prepara la persona en Ajustes y lo manda ella por donde quiera.
- Las horas de cada línea (`t`) son segundos desde que arrancó el puente
  (`a` es un número al azar de ese arranque): con la fecha del archivo no se ve
  a qué hora trabaja nadie.
- Lo escribe sólo el servicio. El MCP le manda lo que tardó cada herramienta
  (`/api/mediciones/herramienta`), y el servicio calcula lo que piensa Claude
  entre una y otra.
- Nada por fotograma ni por captura: lo que pasa muchas veces por segundo
  (fotogramas, tramas, teclas) suma en memoria (`Sumas`) y se vuelca una
  vez por minuto.
- `apuntar` no lanza nunca: medir no puede romper lo que se mide.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import math
import random
import re
import sys
import threading
import time
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from . import config

# ── la lista cerrada ────────────────────────────────────────────────────────
NUMERO = "numero"
SI_NO = "si_no"
# Sólo cifras y puntos («0.5.11», «2.1.322»): la versión del puente, del
# firmware o de Claude Code dice mucho de un fallo y no puede llevar texto.
VERSION = "version"
_VERSION = re.compile(r"\d{1,6}(\.\d{1,6}){0,3}")
# Un número más grande no es una medición: es otra cosa metida aquí.
NUMERO_MAX = 1e12

#: Las herramientas del servidor MCP (`mcp_servidor`). Una prueba comprueba que
#: coinciden con las registradas: una nueva sin apuntar aquí no se mediría.
HERRAMIENTAS = frozenset({
    "estado", "ver_pantalla", "teclear", "atajo", "ir_a_linea", "clic", "recorrer_pantalla", "rueda",
    "despertar_mac", "jiggler", "sondear_teclado", "medir_teclado", "probar_teclado", "comprobar_teclado",
    "leer_documento", "ver_pagina", "transcribir_pagina", "estado_lectura", "resolver_linea", "comprobar_huella",
    "proponer_cambio", "estado_cambio", "escribir_cambio", "ver_tramo",
})

#: Por qué falló una herramienta, por la respuesta del servicio (`mcp_servidor.clase_de_error`).
ERRORES_HERRAMIENTA = frozenset({
    "ninguno", "sin_control", "ocupado", "intraducible", "aparato", "peticion", "no_existe", "prohibido",
    "servicio", "sin_servicio", "tiempo", "local", "otro",
})

#: Por qué volvió el control a la persona (`Puente.devolver_control`, `por=`).
POR_CONTROL = frozenset({
    "fin_turno", "pregunta", "esc", "usar_mac", "retomar", "parar", "caducidad", "respaldo_tarea", "aparato",
    "reunion", "conversacion", "otra_sesion", "otro",
})

#: Por qué no se escribió un cambio (o no se pudo proponer).
FALLOS_CAMBIO = frozenset({"ninguno", "pagina_distinta", "inestable", "sin_control", "dialogo", "intraducible",
                           "otro"})

#: Por qué no conectó el aparato, o por qué se cortó.
MOTIVOS_CONEXION = frozenset({"ninguno", "contrasena", "no_responde", "reposo", "sin_video", "saludo", "canales",
                              "otra_sesion", "video", "conexion", "otro"})

APARATOS = frozenset({"jetkvm", "simulador"})

#: El modelo, por su id de la lista de Ajustes; «el_suyo» es «El de mi Claude Code».
MODELOS = frozenset({m for m, _ in config.MODELOS if m} | {"el_suyo", "otro"})

ESQUEMA: dict[str, dict[str, object]] = {
    # Cada llamada a una herramienta de Claude. `hueco_ms`: desde que acabó la
    # anterior del mismo turno (lo que piensa Claude); en la primera tras un
    # mensaje, `desde_mensaje_ms`.
    "herramienta": {"nombre": HERRAMIENTAS, "ms": NUMERO, "ok": SI_NO, "error": ERRORES_HERRAMIENTA,
                    "hueco_ms": NUMERO, "desde_mensaje_ms": NUMERO, "imagenes": NUMERO, "kb": NUMERO},
    # Cada `Motor.esperar_estable`: cuánto esperó, si se quedó quieta, cuántas
    # capturas comparó y la menor diferencia entre dos seguidas (con la pantalla
    # quieta, el ruido de compresión del vídeo).
    "espera": {"ms": NUMERO, "quieta": SI_NO, "capturas": NUMERO, "dif_min": NUMERO, "tope_ms": NUMERO},
    # Cada `Motor.tras` (C-0485): hasta el primer cambio (`ms_cambio`, null si
    # no cambió), el «antes» asentado (`ms_antes`) y el total.
    "tras": {"ms_cambio": NUMERO, "cambio": SI_NO, "quieta": SI_NO, "antes_quieta": SI_NO, "tope_ms": NUMERO,
             "ms": NUMERO, "ms_antes": NUMERO,
             "clase": frozenset({"inicio", "pagina", "rueda", "dialogo", "otra"})},
    "lectura": {"evento": frozenset({"captura", "transcripcion", "huella"}), "ms": NUMERO, "paginas": NUMERO,
                "inestables": NUMERO, "estado": frozenset({"capturada", "cortada", "error"}), "con_zona": SI_NO,
                "errores": NUMERO, "conflictos": NUMERO, "quien": frozenset({"claude", "persona"}),
                "ok": SI_NO, "completo": SI_NO},
    # `por`: quién aprobó, la persona con su clic o su permiso de correcciones
    # pequeñas (C-0489); `lineas` y `caracteres`, lo que mueve (`cambios.medida`).
    "cambio": {"evento": frozenset({"propuesta", "aprobado", "rechazado", "escritura", "huella"}),
               "tramos": NUMERO, "escritos": NUMERO, "ok": SI_NO, "fallo": FALLOS_CAMBIO, "ms": NUMERO,
               "capturas_inestables": NUMERO, "sin_verificar": SI_NO, "quien": frozenset({"claude", "persona"}),
               "por": frozenset({"persona", "correcciones"}), "lineas": NUMERO, "caracteres": NUMERO},
    # Lo que tecleó Claude en el último minuto (`Sumas`): cuántas, nunca cuáles.
    "teclado": {"s": NUMERO, "pulsaciones": NUMERO, "ms_tecleando": NUMERO},
    "raton": {"s": NUMERO, "movimientos": NUMERO, "clics": NUMERO, "ruedas": NUMERO},
    # El vídeo del último minuto: fotogramas decodificados, tramas H.264 que
    # llegaron, tramas tiradas porque el navegador no daba abasto, cortes, e
    # imágenes hechas para el directo de imágenes.
    "video": {"s": NUMERO, "fotogramas": NUMERO, "fps": NUMERO, "tramas": NUMERO, "descartes": NUMERO,
              "cortes": NUMERO, "imagenes": NUMERO, "modo": frozenset({"h264", "mjpeg"}), "conectado": SI_NO},
    "conexion": {"evento": frozenset({"conectado", "fallo", "vuelta", "corte"}),
                 "por": frozenset({"arranque", "reconectar", "ajustes", "reunion", "sola"}), "ms": NUMERO,
                 "motivo": MOTIVOS_CONEXION, "aparato": APARATOS},
    # Un turno de Claude, de su mensaje a su final: cuántas herramientas, y de
    # ellas cuántas lecturas (para ver lecturas repetidas sin guardar nombres).
    "turno": {"ms": NUMERO, "herramientas": NUMERO, "lecturas": NUMERO, "propuestas": NUMERO, "cambios": NUMERO,
              "otras": NUMERO, "preguntas": NUMERO, "conversacion": SI_NO,
              "fin": frozenset({"stop", "sesion_cerrada", "cortado", "reabierta"})},
    "contexto": {"evento": frozenset({"arranque", "conexion"}), "aparato": APARATOS, "version": VERSION,
                 "firmware": VERSION, "firmware_contrastado": SI_NO, "claude_code": VERSION, "ancho": NUMERO,
                 "alto": NUMERO, "retardo_tecla_ms": NUMERO, "retardo_video_ms": NUMERO, "invertir_rueda": SI_NO,
                 "distribucion": frozenset({"mac-us", "mac-es", "medida"}), "modelo": MODELOS,
                 "saltar_permisos": SI_NO},
    # `correcciones`: si el «dar» trajo el permiso de correcciones pequeñas (C-0489).
    "control": {"evento": frozenset({"dado", "devuelto"}), "por": POR_CONTROL, "ms_con_claude": NUMERO,
                "correcciones": SI_NO},
    # La persona usando el Mac desde el puente: cuánto rato y cuántas veces, nunca qué.
    "mando": {"s": NUMERO, "teclas": NUMERO, "clics": NUMERO, "pegados": NUMERO, "ruedas": NUMERO,
              "combinaciones": NUMERO, "rechazadas": NUMERO, "retomo": SI_NO},
    "calibracion": {"evento": frozenset({"sondeo", "medida", "prueba", "comprobacion"}), "lineas": NUMERO,
                    "caracteres": NUMERO, "filas": NUMERO, "verificados": NUMERO, "no_cuadran": NUMERO,
                    "faltan": NUMERO, "elegible": SI_NO, "ronda": NUMERO, "ok": SI_NO},
}
# Las que lleva cada línea, además de `tipo`.
COMUNES = {"t": NUMERO, "a": NUMERO}

DIAS = 30
_DIA = re.compile(r"(\d{4}-\d{2}-\d{2})\.jsonl")

ARRANQUE = time.monotonic()
ARRANQUE_ID = random.randrange(1, 2**31)

_cerrojo = threading.Lock()
_activas: tuple[tuple, bool] | None = None


class NoValida(ValueError):
    """Una medición que no casa con `ESQUEMA`. El mensaje nunca lleva el valor."""


def _nombre(clave) -> str:
    # El mensaje sale por stderr (al registro del servicio): una clave rara que
    # mande alguien no se copia ahí tal cual.
    return clave if isinstance(clave, str) and re.fullmatch(r"[a-z_]{1,30}", clave) else "(una clave rara)"


def _valido(clase, v) -> bool:
    if v is None:
        return True
    if clase == NUMERO:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= NUMERO_MAX
    if clase == SI_NO:
        return isinstance(v, bool)
    if clase == VERSION:
        return isinstance(v, str) and bool(_VERSION.fullmatch(v))
    return isinstance(v, str) and v in clase  # una lista cerrada


def validar(tipo: str, valores: dict) -> None:
    """Lanza `NoValida` si el tipo no existe, sobra una clave o un valor no es de su clase."""
    if not isinstance(tipo, str) or tipo not in ESQUEMA:
        raise NoValida(f"tipo de medición desconocido: {_nombre(tipo)}")
    if not isinstance(valores, dict):
        raise NoValida("una medición es un diccionario")
    claves = {**ESQUEMA[tipo], **COMUNES}
    for k, v in valores.items():
        if k not in claves:
            raise NoValida(f"«{_nombre(k)}» no es una clave de «{tipo}»")
        if not _valido(claves[k], v):
            raise NoValida(f"«{k}» de «{tipo}» no es {_clase_dicha(claves[k])}")


def _clase_dicha(clase) -> str:
    return {NUMERO: "un número", SI_NO: "un sí o no", VERSION: "un número de versión"}.get(
        clase, "de su lista cerrada")  # type: ignore[arg-type]


def validar_linea(linea: dict) -> None:
    """Una línea tal como queda en el archivo: `tipo` y lo demás."""
    if not isinstance(linea, dict):
        raise NoValida("una línea es un diccionario")
    resto = dict(linea)
    validar(resto.pop("tipo", None), resto)


def carpeta() -> Path:
    return config.hogar() / "mediciones"


def activas() -> bool:
    """El interruptor de Ajustes («Mediciones de uso»), encendido de fábrica.

    Se mira en cada apunte (lo cambia la persona en cualquier momento) sin
    releer el archivo: sólo si cambió su fecha o su tamaño. Unos ajustes que no
    se pueden leer no dejan medir: la persona pudo haberlo apagado."""
    global _activas
    ruta = config.hogar() / "ajustes.json"
    try:
        st = ruta.stat()
        marca: tuple = (str(ruta), st.st_mtime_ns, st.st_size)
    except OSError:
        marca = (str(ruta), None, None)
    if _activas is not None and _activas[0] == marca:
        return _activas[1]
    try:
        valor = config.leer_ajustes().get("mediciones", {}).get("activas", True) is not False
    except Exception:
        valor = False
    _activas = (marca, valor)
    return valor


def _redondear(v):
    return round(v, 3) if isinstance(v, float) else v


def apuntar(tipo: str, **valores) -> bool:
    """Apunta una línea de hoy si las mediciones están encendidas. True si la escribió.

    Nunca lanza: lo que no valida no se escribe y se dice por stderr (sin el
    valor), y un disco lleno tampoco corta lo que se estaba midiendo."""
    try:
        if not activas():
            return False
        valores = {k: _redondear(v) for k, v in valores.items()}
        validar(tipo, valores)
        linea = {"tipo": tipo, "t": round(time.monotonic() - ARRANQUE, 3), "a": ARRANQUE_ID, **valores}
        texto = json.dumps(linea, ensure_ascii=True, separators=(",", ":")) + "\n"
        with _cerrojo:
            destino = carpeta()
            destino.mkdir(parents=True, exist_ok=True)
            with (destino / f"{date.today().isoformat()}.jsonl").open("a") as f:
                f.write(texto)
        return True
    except Exception as e:
        with contextlib.suppress(Exception):  # sin stderr, tampoco se lanza
            print(f"[mediciones] no apunto «{_nombre(tipo)}»: {e if isinstance(e, NoValida) else type(e).__name__}",
                  file=sys.stderr, flush=True)
        return False


def _dias() -> list[tuple[date, Path]]:
    if not carpeta().exists():
        return []
    salida = []
    for f in carpeta().iterdir():
        m = _DIA.fullmatch(f.name)
        if m and f.is_file():
            try:
                salida.append((date.fromisoformat(m.group(1)), f))
            except ValueError:
                continue
    return sorted(salida)


def podar(dias: int = DIAS) -> int:
    """Borra los días de hace más de `dias`. Devuelve cuántos archivos."""
    limite = date.today() - timedelta(days=dias)
    n = 0
    for dia, f in _dias():
        if dia < limite:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def borrar() -> int:
    """Todas las mediciones guardadas (el botón «Borrar mediciones»)."""
    n = 0
    with _cerrojo:
        for _, f in _dias():
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def estado() -> dict:
    """Para Ajustes: el interruptor y cuánto hay guardado («N días, X KB»)."""
    dias = _dias()
    total = 0
    for _, f in dias:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    kb = round(total / 1024, 1)
    if dias:
        texto = (f"Guardadas: {len(dias)} {'día' if len(dias) == 1 else 'días'}, "
                 f"{str(kb).replace('.', ',')} KB.")
    else:
        texto = "Aún no hay mediciones guardadas."
    return {"activas": activas(), "dias": len(dias), "kb": kb, "texto": texto}


# ── el paquete para mandar ──────────────────────────────────────────────────
LEEME = """Mediciones de uso del Puente KVM
================================

Qué es: cuánto tarda cada cosa en el puente y cuántas veces pasa, para mejorar
las esperas y las herramientas con el aparato de verdad delante.

Qué lleva: un archivo por día (mediciones/AAAA-MM-DD.jsonl), una línea JSON por
medición. Cada línea lleva su "tipo" y sólo números, sí/no (true/false),
palabras de una lista cerrada y números de versión. Por ejemplo, cuántos
milisegundos tardó una herramienta, si la pantalla se quedó quieta, o por qué
volvió el control ("fin_turno", "usar_mac"...).

Qué NO lleva: nada de lo que se escribe ni de lo que se lee en el Mac, ni
nombres (de lecturas, cambios, objetos o personas), ni rutas, ni posiciones en
la pantalla, ni imágenes. Las horas son segundos desde que arrancó el puente
("t"); "a" es un número al azar de cada arranque.

Al prepararlo, cada línea se volvió a comprobar contra la lista: lo que no
casaba no entró ({descartadas} {lineas_descartadas}).

Puedes abrir los archivos con cualquier editor de texto y mirarlos antes de
mandarlos. No se manda nada solo: lo mandas tú, por donde quieras.

Días: {dias}. Líneas: {lineas}.
"""


def empaquetar() -> bytes:
    """El .zip para mandar: `LEEME.txt` y los días, cada línea comprobada otra vez.

    Una línea que no se entiende o no casa con `ESQUEMA` (tocada a mano, de una
    versión que apuntaba otra cosa) se queda fuera, y el LEEME dice cuántas."""
    buf = io.BytesIO()
    descartadas = lineas = 0
    dias = _dias()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dia, f in dias:
            buenas = []
            try:
                crudo = f.read_text(errors="replace")
            except OSError:
                continue
            for texto in crudo.splitlines():
                if not texto.strip():
                    continue
                try:
                    linea = json.loads(texto)
                    validar_linea(linea)
                except (ValueError, TypeError):
                    descartadas += 1
                    continue
                buenas.append(json.dumps(linea, ensure_ascii=True, separators=(",", ":")))
            lineas += len(buenas)
            z.writestr(f"mediciones/{dia.isoformat()}.jsonl", "\n".join(buenas) + ("\n" if buenas else ""))
        z.writestr("LEEME.txt", LEEME.format(descartadas=descartadas,
                                             lineas_descartadas="línea" if descartadas == 1 else "líneas",
                                             dias=len(dias), lineas=lineas))
    return buf.getvalue()


# ── leer un paquete recibido ────────────────────────────────────────────────
# Un .zip que llega de fuera: no se lee sin tope.
TOPE_LECTURA = 200 * 1024 * 1024


def leer_paquete(ruta_zip: Path) -> tuple[list[dict], int]:
    """Las líneas válidas de un .zip de `empaquetar` y cuántas no lo eran."""
    lineas: list[dict] = []
    malas = leido = 0
    with zipfile.ZipFile(ruta_zip) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if not _DIA.fullmatch(info.filename.rsplit("/", 1)[-1]) or info.is_dir():
                continue
            leido += info.file_size
            if leido > TOPE_LECTURA:
                raise ValueError(f"el paquete pasa de {TOPE_LECTURA // 2**20} MB descomprimido: no lo leo")
            dia = info.filename.rsplit("/", 1)[-1][:10]
            for texto in z.read(info).decode("utf-8", errors="replace").splitlines():
                if not texto.strip():
                    continue
                try:
                    linea = json.loads(texto)
                    validar_linea(linea)
                except (ValueError, TypeError):
                    malas += 1
                    continue
                linea["_dia"] = dia
                lineas.append(linea)
    return lineas, malas


def percentil(valores: list[float], p: float) -> float | None:
    """Por rango más cercano: un valor que de verdad salió, no uno interpolado."""
    v = sorted(x for x in valores if x is not None)
    if not v:
        return None
    return v[max(0, min(len(v) - 1, math.ceil(p / 100 * len(v)) - 1))]


def _ms(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1000:.1f} s" if v >= 10_000 else f"{v:.0f} ms"


def _cuenta(c: Counter) -> str:
    return ", ".join(f"{k} {n}" for k, n in c.most_common()) or "ninguno"


def resumir(ruta_zip: Path) -> str:
    """Lo que dice un paquete, para leerlo en una terminal (`puente-kvm mediciones resumir`)."""
    lineas, malas = leer_paquete(Path(ruta_zip))
    por_tipo: dict[str, list[dict]] = defaultdict(list)
    for l in lineas:
        por_tipo[l["tipo"]].append(l)
    dias = sorted({l["_dia"] for l in lineas})
    arranques = len({(l["_dia"], l.get("a")) for l in lineas})
    s: list[str] = [f"Mediciones: {len(lineas)} líneas, {len(dias)} días"
                    + (f" ({dias[0]} a {dias[-1]})" if dias else "") + f", {arranques} arranques del puente."]
    if malas:
        s.append(f"  {malas} líneas no casaban con la lista y no se cuentan.")

    for c in por_tipo["contexto"][-1:]:
        s.append(f"Contexto (el último): aparato {c.get('aparato')}, puente {c.get('version')}, firmware "
                 f"{c.get('firmware')}, Claude Code {c.get('claude_code')}, {c.get('ancho')}×{c.get('alto')}, "
                 f"retraso del vídeo {c.get('retardo_video_ms')} ms, pausa entre teclas {c.get('retardo_tecla_ms')} "
                 f"ms, teclado {c.get('distribucion')}, modelo {c.get('modelo')}.")

    h = por_tipo["herramienta"]
    if h:
        s.append("\nHerramientas (llamadas, fallos, p50 / p90 de lo que tardan):")
        grupos: dict[str, list[dict]] = defaultdict(list)
        for l in h:
            grupos[l.get("nombre") or "?"].append(l)
        for nombre, ls in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
            ms = [l.get("ms") for l in ls]
            fallos = Counter(l.get("error") for l in ls if l.get("ok") is False)
            s.append(f"  {nombre:<20} {len(ls):>5}  fallos {sum(fallos.values()):>3}"
                     + (f" ({_cuenta(fallos)})" if fallos else "")
                     + f"  {_ms(percentil(ms, 50))} / {_ms(percentil(ms, 90))}")
        huecos = [l.get("hueco_ms") for l in h if l.get("hueco_ms") is not None]
        primeras = [l.get("desde_mensaje_ms") for l in h if l.get("desde_mensaje_ms") is not None]
        s.append(f"Lo que piensa Claude entre dos herramientas: p50 {_ms(percentil(huecos, 50))}, "
                 f"p90 {_ms(percentil(huecos, 90))} ({len(huecos)} huecos); del mensaje a la primera: "
                 f"p50 {_ms(percentil(primeras, 50))}.")

    t = por_tipo["tras"]
    if t:
        con = [l.get("ms_cambio") for l in t if l.get("cambio")]
        sin = sum(1 for l in t if not l.get("cambio"))
        topes = Counter(l.get("tope_ms") for l in t)
        s.append(f"\nTras pulsar (tras): {len(t)} veces, {sin} sin cambio en el tope "
                 f"(tope más usado {topes.most_common(1)[0][0]} ms).")
        s.append(f"  Hasta ver el cambio: p50 {_ms(percentil(con, 50))}, p90 {_ms(percentil(con, 90))}, "
                 f"p99 {_ms(percentil(con, 99))}, máximo {_ms(max(con) if con else None)}.")
        tramos = [(0, 500), (500, 1000), (1000, 2000), (2000, 3000), (3000, None)]
        partes = []
        for desde, hasta in tramos:
            n = sum(1 for v in con if v >= desde and (hasta is None or v < hasta))
            partes.append(f"{desde / 1000:g}–{hasta / 1000:g} s: {n}" if hasta else f"≥{desde / 1000:g} s: {n}")
        s.append("  Reparto: " + "; ".join(partes) + ".")
        por_clase = Counter(l.get("clase") for l in t)
        s.append(f"  Por clase: {_cuenta(por_clase)}. Con el «antes» sin asentar: "
                 f"{sum(1 for l in t if l.get('antes_quieta') is False)}.")
        antes = [l.get("ms_antes") for l in t]
        s.append(f"  Esperando el «antes» asentado: p50 {_ms(percentil(antes, 50))}, p90 {_ms(percentil(antes, 90))}.")

    e = por_tipo["espera"]
    if e:
        quietas = [l for l in e if l.get("quieta")]
        ruido = [l.get("dif_min") for l in quietas]
        s.append(f"\nEsperas a pantalla quieta: {len(e)}, {len(e) - len(quietas)} sin quedarse quieta; "
                 f"ruido entre dos quietas p50 {percentil(ruido, 50)}, p90 {percentil(ruido, 90)} "
                 f"(el umbral es 0.03).")

    co = por_tipo["control"]
    if co:
        devueltos = [l for l in co if l.get("evento") == "devuelto"]
        con_claude = [l.get("ms_con_claude") for l in devueltos]
        s.append(f"\nControl: dado {sum(1 for l in co if l.get('evento') == 'dado')} veces, devuelto "
                 f"{len(devueltos)} ({_cuenta(Counter(l.get('por') for l in devueltos))}); con Claude p50 "
                 f"{_ms(percentil(con_claude, 50))}, p90 {_ms(percentil(con_claude, 90))}.")

    tu = por_tipo["turno"]
    if tu:
        herr = [l.get("herramientas") for l in tu]
        repetidas = sum(1 for l in tu if (l.get("lecturas") or 0) > 1)
        s.append(f"\nTurnos de Claude: {len(tu)} ({_cuenta(Counter(l.get('fin') for l in tu))}); duran p50 "
                 f"{_ms(percentil([l.get('ms') for l in tu], 50))}; herramientas por turno p50 "
                 f"{percentil(herr, 50)}, máximo {max((x for x in herr if x is not None), default=None)}; "
                 f"turnos con más de una lectura: {repetidas}.")

    le = por_tipo["lectura"]
    if le:
        capt = [l for l in le if l.get("evento") == "captura"]
        hu = [l for l in le if l.get("evento") == "huella"]
        tr = [l for l in le if l.get("evento") == "transcripcion"]
        s.append(f"\nLecturas: {len(capt)} capturas ({_cuenta(Counter(l.get('estado') for l in capt))}), "
                 f"{sum(l.get('paginas') or 0 for l in capt)} páginas, "
                 f"{sum(l.get('inestables') or 0 for l in capt)} inestables; páginas transcritas {len(tr)}, con "
                 f"errores {sum(1 for l in tr if l.get('errores'))}; huellas {len(hu)}, cuadraron "
                 f"{sum(1 for l in hu if l.get('ok'))}.")

    ca = por_tipo["cambio"]
    if ca:
        esc = [l for l in ca if l.get("evento") == "escritura"]
        fallos = Counter(l.get("fallo") for l in esc if not l.get("ok"))
        hu = [l for l in ca if l.get("evento") == "huella"]
        apr = [l for l in ca if l.get("evento") == "aprobado"]
        s.append(f"\nCambios: {sum(1 for l in ca if l.get('evento') == 'propuesta')} propuestos, "
                 f"{len(apr)} aprobados ({sum(1 for l in apr if l.get('por') == 'correcciones')} por el permiso "
                 f"de correcciones pequeñas), {len(esc)} escrituras, fallidas {sum(fallos.values())} ({_cuenta(fallos)}); huellas "
                 f"{len(hu)}, cuadraron {sum(1 for l in hu if l.get('ok'))}.")

    v = por_tipo["video"]
    if v:
        fps = [l.get("fps") for l in v if l.get("conectado") and l.get("fps") is not None]
        s.append(f"\nVídeo: fps por minuto conectado p50 {percentil(fps, 50)}, mínimo "
                 f"{min(fps) if fps else None}; cortes {sum(l.get('cortes') or 0 for l in v)}, tramas tiradas "
                 f"{sum(l.get('descartes') or 0 for l in v)}.")
    cx = por_tipo["conexion"]
    if cx:
        s.append(f"Conexiones: {_cuenta(Counter(l.get('evento') for l in cx))}; motivos de fallo o corte: "
                 f"{_cuenta(Counter(l.get('motivo') for l in cx if l.get('evento') in ('fallo', 'corte')))}.")

    te, ra = por_tipo["teclado"], por_tipo["raton"]
    if te or ra:
        pul = sum(l.get("pulsaciones") or 0 for l in te)
        ms = sum(l.get("ms_tecleando") or 0 for l in te)
        s.append(f"\nClaude en el Mac: {pul} pulsaciones" + (f" (unas {pul / ms * 1000:.0f} por segundo tecleando)"
                                                             if ms else "")
                 + f", {sum(l.get('clics') or 0 for l in ra)} clics, {sum(l.get('ruedas') or 0 for l in ra)} "
                   "giros de rueda.")
    m = por_tipo["mando"]
    if m:
        s.append(f"La persona desde el puente: {len(m)} veces, {sum(l.get('s') or 0 for l in m) / 60:.0f} min, "
                 f"{sum(l.get('teclas') or 0 for l in m)} teclas, {sum(l.get('clics') or 0 for l in m)} clics, "
                 f"{sum(l.get('pegados') or 0 for l in m)} pegados; le quitó el control a Claude "
                 f"{sum(1 for l in m if l.get('retomo'))} veces.")
    cal = por_tipo["calibracion"]
    if cal:
        s.append(f"Calibración del teclado: {_cuenta(Counter(l.get('evento') for l in cal))}; filas que no "
                 f"cuadraron {sum(l.get('no_cuadran') or 0 for l in cal)}.")
    return "\n".join(s) + "\n"


# ── lo que pasa muchas veces por segundo ────────────────────────────────────
GRUPOS = {
    "video": ("fotogramas", "tramas", "descartes", "cortes", "imagenes"),
    "teclado": ("pulsaciones", "ms_tecleando"),
    "raton": ("movimientos", "clics", "ruedas"),
}


class Sumas:
    """Sumas en memoria, volcadas una vez por minuto (`volcar`).

    Un fotograma, una trama o una tecla no escriben nada: suman uno. Escribir
    por cada fotograma serían 30 líneas por segundo, y el disco y el bucle que
    atiende el ratón de la persona lo notarían."""

    def __init__(self) -> None:
        self._n: Counter = Counter()
        self._desde = time.monotonic()
        self._cerrojo = threading.Lock()

    def sumar(self, nombre: str, n: float = 1) -> None:
        with self._cerrojo:
            self._n[nombre] += n

    def volcar(self, video: dict | None = None) -> int:
        """Una línea por grupo con algo que contar, y a cero. Devuelve cuántas escribió.

        La de vídeo sale también sin nada si el aparato estaba conectado: cero
        fotogramas con conexión es justo lo que hay que ver."""
        with self._cerrojo:
            n, self._n = self._n, Counter()
            ahora = time.monotonic()
            s, self._desde = ahora - self._desde, ahora
        escritas = 0
        for tipo, claves in GRUPOS.items():
            valores = {k: round(n.get(k, 0)) for k in claves}
            extra = {}
            if tipo == "video":
                extra = dict(video or {})
                if not any(valores.values()) and not extra.get("conectado"):
                    continue
                valores["fps"] = round(valores["fotogramas"] / s, 2) if s > 0 else None
            elif not any(valores.values()):
                continue
            if apuntar(tipo, s=round(s, 1), **valores, **extra):
                escritas += 1
        return escritas


SUMAS = Sumas()
VOLCADO_S = 60.0


async def volcar_siempre(sumas: Sumas, video: Callable[[], dict], intervalo: float = VOLCADO_S) -> None:
    """La tarea de fondo del servicio: cada `intervalo`, `sumas.volcar`.

    No puede morir por una vuelta mala (un aparato que no contesta su estado, un
    disco lleno): se dice y se sigue. Sólo la para que la cancelen."""
    while True:
        await asyncio.sleep(intervalo)
        try:
            try:
                extra = video()
            except Exception as e:
                extra = {}
                print(f"[mediciones] sin el estado del vídeo para el volcado: {type(e).__name__}", file=sys.stderr,
                      flush=True)
            sumas.volcar(extra)
        except Exception as e:
            with contextlib.suppress(Exception):  # sin stderr, tampoco se lanza
                print(f"[mediciones] el volcado falló: {type(e).__name__}", file=sys.stderr, flush=True)
