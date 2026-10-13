"""Cuánto se ha gastado en cada proyecto, leído del registro de Claude Code.

El hub no mide esto: lo **lee**. Claude Code deja un `.jsonl` por sesión en
`~/.claude/projects/`, y cada mensaje del asistente trae su bloque `usage` con
los cuatro recuentos y el `cwd` desde el que se pidió. Con eso y el
`Atribuidor` que ya reparte paneles entre proyectos (una sola costura, no dos)
sale el consumo por proyecto sin inventar nada.

🔴 **Sumar en crudo infla 1.86x, y no de forma pareja.** Una respuesta se
escribe en el registro partida en VARIAS líneas —una por bloque de contenido:
pensar, texto, cada llamada a una herramienta— y **todas repiten el mismo
`usage`**. Medido sobre el registro entero: 144 527 mensajes para 73 291
peticiones de verdad, o sea 71 264 apariciones de más. Sumar línea a línea daría
2,77x en entrada, 2,46x en escritura de caché, 1,85x en lectura y 1,47x en
salida — ni siquiera se podría corregir con un factor.

La regla para deduplicar salió de mirar los datos, no de suponerla:

- Los tres recuentos de entrada (`input`, `cache_creation`, `cache_read`)
  describen la petición y son **idénticos** en todas sus líneas. Comprobado:
  **0 peticiones** de 73 291 rompen la invariante.
- `output_tokens` va **creciendo** línea a línea: es el recuento parcial según
  se emitía. El bueno es el último, o sea el **máximo**.

Así que se agrupa por `requestId` y se toma el máximo de cada campo. Es exacto,
no una aproximación.

🔴 **Y es una ventana rodante de 30 días, no el histórico.** Claude Code poda
los transcripts —el registro empieza el 2026-08-10 y el día que se midió era el
2026-09-10, 31 días justos—, así que estas cifras son «lo último que queda en el
registro», jamás «todo lo que has gastado». La pantalla lo dice con las fechas
que salen del propio registro, porque una cifra sin su ventana es una cifra que
alguien va a leer como total.

**No hay dinero en este módulo, a propósito.** Convertir tokens a euros pide una
tabla de precios por modelo que cambia sola y que el hub no puede verificar
contra nada; sería justo la cifra que no se puede defender (regla dura 13). Se
dan los tokens por tipo, que es lo que sí está medido.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .registry import Atribuidor, Proyecto


class ConsumoNoMedido(RuntimeError):
    """No se pudo leer el registro. Se conserva la última medición."""


# Cuánto se le deja tardar. Si se pasa **no se escribe nada**: un recuento a
# medias se lee igual que uno completo y diría que un proyecto gastó menos.
# Frente a eso, conservar la cifra de hace diez minutos es estrictamente mejor.
PRESUPUESTO_SEGUNDOS = 60

# Los cuatro recuentos, con el nombre que llevan en el registro y el que llevan
# aquí. `razonado` va aparte porque está DENTRO de la salida, no al lado: sumarlo
# al total lo contaría dos veces.
CAMPOS = (
    ("input_tokens", "entrada"),
    ("cache_creation_input_tokens", "escritura"),
    ("cache_read_input_tokens", "lectura"),
    ("output_tokens", "salida"),
)


# ── Cómo se escriben las cifras ──────────────────────────────────────────────
#
# En castellano: punto de millar y coma decimal. Se mezclaron las dos
# convenciones en la misma tabla —`73,353` peticiones al lado de `13,3 G` de
# caché— y la coma quería decir una cosa distinta a dos columnas de distancia.

def numero(n: int | float | None, decimales: int = 0) -> str:
    """Una cifra exacta. Para lo que se lee al dígito, como las peticiones."""
    if n is None:
        return "—"
    return f"{n:,.{decimales}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def millones(n: int | None) -> str:
    """Una cifra grande en la escala en que se lee de un vistazo.

    13 655 752 110 no se lee: se cuenta con el dedo. Y estas cifras se comparan
    entre sí —qué proyecto pesa más—, no se auditan al token.

    Un decimal por debajo de 100 y ninguno por encima: «8,5 G» dice algo y
    «845,3 M» ya no — el decimal de una cifra de tres dígitos es ruido con
    aspecto de precisión.
    """
    if n is None:
        return "—"
    for corte, sufijo in ((1_000_000_000, "G"), (1_000_000, "M"), (1_000, "k")):
        # El umbral cede lo que va a ceder el redondeo. Con `>= corte` a secas,
        # 999 999 no llegaba a «M» y salía como «999.999» entre cifras que van
        # en M: la escala cambiando a mitad de columna es justo lo que esto
        # existe para evitar.
        if abs(n) < corte * 0.9995:
            continue
        valor = n / corte
        texto = f"{valor:.1f}" if abs(valor) < 100 else f"{valor:.0f}"
        return texto.replace(".", ",") + " " + sufijo
    return numero(n)


def carpeta() -> Path:
    """Dónde deja Claude Code sus transcripts.

    Función y no constante por lo mismo que `acceso.archivo()`: se puede apuntar
    a otro sitio con `HUB_TRANSCRIPTS` —los tests lo hacen— y una constante
    evaluada al importar se quedaría con la respuesta vieja.
    """
    declarado = os.environ.get("HUB_TRANSCRIPTS")
    return Path(declarado) if declarado else Path.home() / ".claude" / "projects"


def _peticiones(raiz: Path, limite: float) -> dict[str, dict]:
    """Una entrada por petición de verdad, con el máximo de cada contador.

    La clave es el `requestId`. Los poquísimos mensajes que no lo traen —16 de
    144 527— caen a su `uuid`, que es único por línea: cuentan como una petición
    cada uno, que es lo más cerca de la verdad que se puede estar sin él.

    El agrupado es **global y no por archivo** a propósito: 52 peticiones
    aparecen repartidas entre dos archivos porque la sesión se reanudó, y
    deduplicar dentro de cada archivo las contaría dos veces.
    """
    fuera: dict[str, dict] = {}
    for archivo in sorted(raiz.rglob("*.jsonl")):
        if time.monotonic() > limite:
            raise ConsumoNoMedido(
                f"leer el registro pasó de {PRESUPUESTO_SEGUNDOS}s. No se escribe "
                "un recuento a medias: se conserva la última medición."
            )
        try:
            manejador = archivo.open(encoding="utf-8", errors="replace")
        except OSError:
            continue  # un archivo ilegible no puede dejar sin medir a los demás
        with manejador:
            for linea in manejador:
                # Se filtra por el primer carácter antes de parsear: son 291 000
                # líneas y `json.loads` sobre las que no son objeto es lo único
                # caro de todo el recorrido.
                if not linea.startswith("{"):
                    continue
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if dato.get("type") != "assistant":
                    continue
                mensaje = dato.get("message") or {}
                uso = mensaje.get("usage")
                if not uso:
                    continue
                clave = dato.get("requestId") or f"uuid:{dato.get('uuid', '')}"
                marca = str(dato.get("timestamp") or "")
                fila = fuera.get(clave)
                if fila is None:
                    fila = fuera[clave] = {
                        "ruta": dato.get("cwd") or "",
                        "dia": marca[:10],
                        "modelo": str(mensaje.get("model") or "?"),
                        "cuando": marca,
                        "razonado": 0,
                        **{col: 0 for _, col in CAMPOS},
                    }
                for origen, col in CAMPOS:
                    fila[col] = max(fila[col], uso.get(origen) or 0)
                detalles = uso.get("output_tokens_details") or {}
                fila["razonado"] = max(fila["razonado"],
                                       detalles.get("thinking_tokens") or 0)
    return fuera


def escanear(con: sqlite3.Connection, proyectos: list[Proyecto]) -> int:
    """Repuebla la tabla `consumo` leyendo el registro entero.

    Derivado de archivos, como el catálogo y los repos: se borra y se rehace
    (regla dura 1). Borrar la base y volver a arrancar da exactamente esto.

    La atribución se recalcula en cada escaneo en vez de guardarse para siempre,
    así que dar de alta un proyecto en `projects.yml` reclasifica su historia
    sola en el siguiente ciclo lento — sin rescatar nada a mano.
    """
    raiz = carpeta()
    if not raiz.is_dir():
        raise ConsumoNoMedido(
            f"no hay registro de Claude Code en {raiz}. Se conserva la última "
            "medición."
        )

    peticiones = _peticiones(raiz, time.monotonic() + PRESUPUESTO_SEGUNDOS)
    if not peticiones:
        raise ConsumoNoMedido(
            f"{raiz} existe pero no tiene ni una petición legible. Se conserva la "
            "última medición: un cero aquí es indistinguible de «no he mirado»."
        )

    atribuidor = Atribuidor(proyectos)
    medido_en = datetime.now(timezone.utc).isoformat()
    agregado: dict[tuple, dict] = {}
    for fila in peticiones.values():
        clave = (fila["ruta"], fila["dia"], fila["modelo"])
        acumulado = agregado.setdefault(
            clave, {"peticiones": 0, "razonado": 0, "razonadas": 0,
                    "desde": fila["cuando"],
                    "hasta": fila["cuando"], **{col: 0 for _, col in CAMPOS}}
        )
        acumulado["peticiones"] += 1
        acumulado["razonado"] += fila["razonado"]
        acumulado["razonadas"] += 1 if fila["razonado"] else 0
        for _, col in CAMPOS:
            acumulado[col] += fila[col]
        if fila["cuando"]:
            acumulado["desde"] = min(acumulado["desde"] or fila["cuando"], fila["cuando"])
            acumulado["hasta"] = max(acumulado["hasta"], fila["cuando"])

    con.execute("DELETE FROM consumo")
    for (ruta, dia, modelo), v in agregado.items():
        con.execute(
            """INSERT INTO consumo (proyecto_id, ruta, dia, modelo, peticiones,
                                    entrada, escritura, lectura, salida, razonado,
                                    razonadas, desde, hasta, medido_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (atribuidor.atribuir(ruta) if ruta else None, ruta, dia, modelo,
             v["peticiones"], v["entrada"], v["escritura"], v["lectura"],
             v["salida"], v["razonado"], v["razonadas"], v["desde"], v["hasta"],
             medido_en),
        )
    return len(agregado)


# ── El mismo dato desde una terminal ─────────────────────────────────────────

def _cli(argv: list[str] | None = None) -> int:
    """`uv run python -m hub.consumo` — el reparto, sin abrir el navegador.

    Existe porque la pregunta «¿en qué se está yendo?» se hace a menudo desde la
    terminal en la que se está trabajando, y abrir una pestaña para leer doce
    filas es más rodeo que respuesta. Mide en el momento en vez de leer la tabla:
    desde una shell son 5 s y así no depende de cuándo pasó el ciclo lento.
    """
    import argparse

    from . import db, registry

    partes = argparse.ArgumentParser(
        prog="python -m hub.consumo",
        description="Cuántos tokens ha costado cada proyecto, según el registro "
                    "de Claude Code. Mide en el momento y actualiza la base.")
    partes.parse_args(argv)

    con = db.abrir()
    try:
        try:
            escanear(con, registry.cargar())
        except ConsumoNoMedido as exc:
            print(f"\n  {exc}\n")
            return 1

        from .api import consumo as leer
        datos = leer(con)
        t = datos["totales"]
        print(f"\n  Del {datos['desde'][:10]} al {datos['hasta'][:10]} "
              f"({len(datos['por_dia'])} días; Claude Code poda su registro, "
              f"así que esto no es el histórico).\n")
        print(f"  {'proyecto':<24}{'peticiones':>12}{'salida':>12}"
              f"{'caché escr.':>14}{'caché leída':>14}{'parte':>8}")
        print("  " + "─" * 84)
        for e in datos["proyectos"]:
            print(f"  {e['nombre'][:23]:<24}{numero(e['peticiones']):>12}"
                  f"{millones(e['salida']):>12}{millones(e['escritura']):>14}"
                  f"{millones(e['lectura']):>14}{numero(e['parte'], 1):>7}%")
        print("  " + "─" * 84)
        print(f"  {'TOTAL':<24}{numero(t['peticiones']):>12}{millones(t['salida']):>12}"
              f"{millones(t['escritura']):>14}{millones(t['lectura']):>14}"
              f"{'100,0%':>8}\n")
        # 🔴 Se dice que escribe, porque escribe. La primera versión llevaba un
        # `--guardar` y sin él anunciaba «medido y NO guardado»: mentira, porque
        # `db.conectar` abre con `isolation_level=None` y cada `INSERT` se
        # confirma solo. Un flag que no hace nada y un mensaje que dice lo
        # contrario de lo que pasa es peor que no tener ninguno de los dos.
        print("  Medido ahora, y la pantalla /consumo ya enseña estas mismas "
              "cifras.\n")
        return 0
    finally:
        con.close()


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(_cli())
