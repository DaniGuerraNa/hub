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

**Sólo se relee el transcript que cambió** (C-0326; es la decisión 410
aplicada aquí). El escaneo releía el registro entero cada diez minutos —1,8 GB
en 1 003 archivos, medido el 13-nov— para añadir lo de los últimos diez, en los
que cambian unos ocho archivos (37 MB). Ahora lo que se saca de cada archivo
(`_de_archivo`) se recuerda en la memoria del proceso mientras el archivo
tenga la misma huella (`hub.recordar.por_archivo`), y cada escaneo sólo funde
esos resultados. El agrupado sigue siendo global; por qué fundir da lo mismo
que leerlo todo está en `_peticiones` y lo prueba
`test_la_tabla_es_la_misma_recordando_que_leyendo_todo`.

Lo que se descartó, para que nadie lo «mejore» sin saberlo:

- **Leer sólo lo añadido (desplazamientos).** Trae tres formas nuevas de no
  coincidir con la pasada completa: la última línea a medio escribir, un
  archivo reescrito en el sitio, y contar bytes donde se leen caracteres. Un
  archivo que cambió se relee entero: el mayor pesa 137 MB.
- **Una tabla con el estado.** Es memoria del proceso: al reiniciar el
  muestreo, el primer escaneo lee todo, que es lo que antes costaba cada uno.
- **Una pasada completa al día para la poda.** Sobra: un transcript podado
  deja de salir en el recorrido y ya no se funde.
- **Un conjunto global de `requestId` ya vistos.** No se le puede restar un
  archivo podado, y la petición heredaría ruta, día y modelo del archivo que
  se leyó primero en el tiempo, no del primero en orden.

**No hay dinero en este módulo, a propósito.** Convertir tokens a euros pide una
tabla de precios por modelo que cambia sola y que el hub no puede verificar
contra nada; sería justo la cifra que no se puede defender (regla dura 13). Se
dan los tokens por tipo, que es lo que sí está medido.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db, recordar, transcripts
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


# Cómo se guarda lo leído de una petición en un archivo: una tupla y no un
# diccionario porque se recuerdan todas las de todos los transcripts (decenas
# de miles), y porque una tupla no se puede modificar por descuido al fundir.
# Primero lo que es de la primera línea vista; después los recuentos, que son
# máximos, en el orden de `_RECUENTOS`.
_DE_LA_PRIMERA = ("ruta", "dia", "modelo", "cuando")
_RECUENTOS = ("razonado", *(col for _, col in CAMPOS))


def _internar(valor):
    """La misma cadena, una sola vez en memoria: hay un puñado de rutas,
    modelos y días para decenas de miles de peticiones. Lo que no sea una
    cadena (una línea estropeada) pasa tal cual, como antes."""
    return sys.intern(valor) if type(valor) is str else valor


def _de_archivo(archivo: Path) -> dict[str, tuple] | None:
    """Las peticiones de UN transcript: clave → fila compacta, en el orden en
    que aparecen. De cada una, la ruta, el día, el modelo y la hora de su
    primera línea en este archivo y el máximo de cada contador.

    `{}` si no trae ninguna y `None` sólo si no se pudo abrir: `recordar` no
    guarda un `None`, así que un archivo ilegible se reintenta en el escaneo
    siguiente en vez de quedarse fuera hasta que cambie.

    Función de módulo y sin más argumento que el archivo: es el lector que
    `recordar.por_archivo` distingue por su nombre.
    """
    try:
        manejador = archivo.open(encoding="utf-8", errors="replace")
    except OSError:
        return None  # un archivo ilegible no puede dejar sin medir a los demás
    fijos: dict[str, tuple] = {}
    recuentos: dict[str, list[int]] = {}
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
            cuenta = recuentos.get(clave)
            if cuenta is None:
                marca = str(dato.get("timestamp") or "")
                fijos[clave] = (_internar(dato.get("cwd") or ""), _internar(marca[:10]),
                                _internar(str(mensaje.get("model") or "?")), marca)
                cuenta = recuentos[clave] = [0] * len(_RECUENTOS)
            detalles = uso.get("output_tokens_details") or {}
            cuenta[0] = max(cuenta[0], detalles.get("thinking_tokens") or 0)
            for i, (origen, _) in enumerate(CAMPOS, start=1):
                cuenta[i] = max(cuenta[i], uso.get(origen) or 0)
    return {clave: (*fijos[clave], *cuenta) for clave, cuenta in recuentos.items()}


def _peticiones(raiz: Path, limite: float) -> dict[str, dict]:
    """Una entrada por petición de verdad, con el máximo de cada contador.

    La clave es el `requestId`. Los poquísimos mensajes que no lo traen —16 de
    144 527— caen a su `uuid`, que es único por línea: cuentan como una petición
    cada uno, que es lo más cerca de la verdad que se puede estar sin él.

    El agrupado es **global y no por archivo** a propósito: 52 peticiones
    aparecen repartidas entre dos archivos porque la sesión se reanudó, y
    deduplicar dentro de cada archivo las contaría dos veces.

    🔴 **Por qué fundir lo de cada archivo da lo mismo que leerlo todo seguido**
    (regla dura 19; antes de C-0326 se plegaban las líneas una a una sobre
    este mismo diccionario). Los archivos se recorren en el mismo orden,
    `sorted`. De cada petición:

    - los recuentos son un máximo sobre todas sus líneas, y el máximo de
      todas es el máximo de los máximos de cada archivo;
    - ruta, día, modelo y hora son de la primera línea vista, que es la
      primera del primer archivo, en ese orden, que la trae: justo lo que
      queda al fundir en orden sin pisar lo que ya está.

    Y las peticiones salen en el mismo orden (el de su primera aparición), así
    que el agregado se arma igual. El único supuesto es el de `recordar`: un
    archivo con la misma huella —fecha, tamaño e inodo— tiene el mismo
    contenido.

    Lo recordado no se toca: cada fila de aquí es un diccionario nuevo, y por
    eso se pide sin `copia`.
    """
    archivos = sorted(raiz.rglob("*.jsonl"))
    # El doble de lo que hay: caben todos —con menos, un recorrido en orden
    # no acertaría nunca (`recordar.por_archivo`)— con holgura para los que
    # aparezcan a mitad.
    tope = max(recordar.TOPE, 2 * len(archivos))
    fuera: dict[str, dict] = {}
    for archivo in archivos:
        if time.monotonic() > limite:
            # Lo leído hasta aquí queda recordado: el escaneo siguiente no
            # empieza de cero, y un registro que no cabe en una vuelta se
            # acaba de leer en la otra.
            raise ConsumoNoMedido(
                f"leer el registro pasó de {PRESUPUESTO_SEGUNDOS}s. No se escribe "
                "un recuento a medias: se conserva la última medición."
            )
        del_archivo = recordar.por_archivo(archivo, _de_archivo, tope=tope)
        if del_archivo is None:
            continue
        for clave, compacta in del_archivo.items():
            fila = fuera.get(clave)
            if fila is None:
                fuera[clave] = dict(zip(_DE_LA_PRIMERA + _RECUENTOS, compacta))
                continue
            for col, valor in zip(_RECUENTOS, compacta[len(_DE_LA_PRIMERA):]):
                if valor > fila[col]:
                    fila[col] = valor
    # Lo de un transcript podado se suelta ya, sin esperar a que el tope lo
    # eche. Sólo aquí, con la lista recorrida entera: cortado por el
    # presupuesto no se suelta nada.
    recordar.quedarse_con(_de_archivo, archivos)
    return fuera


def _agregar(peticiones: dict[str, dict]) -> dict[tuple, dict]:
    """Las peticiones, sumadas por (ruta, día, modelo). Puro: ni lee ni escribe."""
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
    return agregado


def escanear(con: sqlite3.Connection, proyectos: list[Proyecto]) -> int:
    """Repuebla la tabla `consumo` con el registro entero.

    Derivado de archivos, como el catálogo y los repos: se borra y se rehace
    (regla dura 1). Borrar la base y volver a arrancar da exactamente esto.
    Entero, pero sin releerlo entero: de un escaneo al siguiente sólo se lee
    el transcript que cambió (`_peticiones`, C-0326).

    La atribución se recalcula en cada escaneo en vez de guardarse para siempre,
    así que dar de alta un proyecto en `projects.yml` reclasifica su historia
    sola en el siguiente ciclo lento — sin rescatar nada a mano.
    """
    raiz = transcripts.raiz()
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
    agregado = _agregar(peticiones)

    # En una transacción (C-0429): el ciclo lento escribe desde su hilo y la
    # web lee desde otro proceso; en autocommit, entre el DELETE y los INSERT
    # quien leyera veía la tabla vacía. En WAL, el lector ve lo de antes,
    # entero, hasta el COMMIT. Si quien llama ya tiene una abierta, en la suya.
    with contextlib.nullcontext() if con.in_transaction else db.transaccion(con):
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
