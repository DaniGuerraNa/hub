"""Repetir un flujo, paso a paso, y pararse en cuanto algo no cuadra.

Determinista a propósito: no hay un modelo dentro que «arregle» un paso que no
encuentra. Si falla, deja `fallo.json` —qué paso, qué error, qué se veía— y
Claude, en la sesión y con el dueño delante, propone el cambio al flujo. Un
reproductor que se corrige solo hace cosas que nadie revisó.
"""
import argparse
import getpass
import json
import sys
import time
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from .flujo import sustituir
from .guardian import DATOS, vigilado

SALIDAS = DATOS / "salidas"


def localizar(page, d: dict):
    if "rol" in d:
        kw = {"name": d["nombre"]} if "nombre" in d else {}
        if d.get("exacto"):
            kw["exact"] = True
        loc = page.get_by_role(d["rol"], **kw)
    elif "etiqueta" in d:
        loc = page.get_by_label(d["etiqueta"], exact=d.get("exacto", False))
    elif "texto" in d:
        loc = page.get_by_text(d["texto"], exact=d.get("exacto", False))
    elif "marcador" in d:
        loc = page.get_by_placeholder(d["marcador"])
    elif "testid" in d:
        loc = page.get_by_test_id(d["testid"])
    elif "css" in d:
        loc = page.locator(d["css"])
    else:
        raise ValueError(f"paso sin localizador: {d}")
    return loc.nth(d["n"]) if "n" in d else loc


def elegir(page, d: dict, espera_ms: int):
    """El localizador principal y, si no aparece, sus alternativas por orden."""
    candidatos = [d] + [{**a} for a in d.get("alternativas", [])]
    fin = time.monotonic() + espera_ms / 1000
    while True:
        for c in candidatos:
            loc = localizar(page, c)
            if loc.count() == 1 or ("n" in c and loc.count() > 0):
                return loc
        if time.monotonic() > fin:
            vistos = {json.dumps({k: v for k, v in c.items() if k != "alternativas"}, ensure_ascii=False):
                      localizar(page, c).count() for c in candidatos}
            raise LookupError(f"ningún localizador da exactamente un elemento: {vistos}")
        time.sleep(0.2)


def tabla(page, nombre: str) -> list[dict]:
    t = page.get_by_role("table", name=nombre)
    cab = [c.inner_text().strip() for c in t.locator("thead th").all()]
    filas = []
    for tr in t.locator("tbody tr").all():
        celdas = [c.inner_text().strip() for c in tr.locator("td").all()]
        filas.append(dict(zip(cab, celdas)) if cab and len(cab) == len(celdas) else {"celdas": celdas})
    return filas


MAX_ANIDADO = 6


def cargar_fragmento(nombre: str, con: dict) -> list:
    """Los pasos de otro flujo, con SUS parámetros resueltos desde `con` y sus
    valores por defecto. Lo que falte se queda como `{{x}}` y revienta al usarse,
    que es mejor que entrar en la pantalla equivocada."""
    from .config import buscar_flujo
    f = yaml.safe_load(buscar_flujo(nombre).read_text()) or {}
    params = {k: d["defecto"] for k, d in (f.get("parametros") or {}).items() if (d or {}).get("defecto")}
    params.update({k: v for k, v in (con or {}).items()})
    return sustituir(f.get("pasos") or [], params)


def ejecutar(page, pasos: list, espera_ms: int, salida: Path, traza: list, datos=None, nivel: int = 0) -> dict:
    datos = {} if datos is None else datos
    if nivel > MAX_ANIDADO:
        raise RecursionError(f"más de {MAX_ANIDADO} fragmentos anidados: ¿uno se usa a sí mismo?")
    for i, paso in enumerate(pasos, 1):
        verbo, arg = next(iter(paso.items()))
        t0 = time.monotonic()
        if verbo == "ir":
            page.goto(arg)
        elif verbo in ("pulsar", "doble_clic", "marcar", "desmarcar", "encima"):
            loc = elegir(page, arg, espera_ms)
            {"pulsar": loc.click, "doble_clic": loc.dblclick, "marcar": loc.check,
             "desmarcar": loc.uncheck, "encima": loc.hover}[verbo]()
        elif verbo == "rellenar":
            elegir(page, arg, espera_ms).fill(arg["valor"])
        elif verbo == "tecla":
            elegir(page, arg, espera_ms).press(arg["tecla"])
        elif verbo == "elegir":
            elegir(page, arg, espera_ms).select_option(label=arg["valor"])
        elif verbo == "esperar":
            ms = arg.get("ms_max", espera_ms)
            if "texto" in arg:
                page.get_by_text(arg["texto"]).first.wait_for(timeout=ms)
            elif "url" in arg:
                page.wait_for_url(arg["url"], timeout=ms)
            elif "ms" in arg:
                page.wait_for_timeout(arg["ms"])
            else:
                elegir(page, arg, ms)
        elif verbo == "extraer":
            if "tabla" in arg:
                datos[arg["a"]] = tabla(page, arg["tabla"])
            else:
                datos[arg["a"]] = elegir(page, arg, espera_ms).inner_text()
        elif verbo == "usar":
            # Un fragmento dentro de otro: así una pantalla con n flujos se
            # reutiliza sin copiar sus pasos en cada flujo que pase por ella.
            arg = {"flujo": arg} if isinstance(arg, str) else arg
            sub = datos if not arg.get("a") else {}
            ejecutar(page, cargar_fragmento(arg["flujo"], arg.get("con") or {}), espera_ms, salida,
                     traza, sub, nivel + 1)
            if arg.get("a"):
                datos[arg["a"]] = sub
        elif verbo == "para_cada":
            # Recorrer lo extraído antes (p. ej. la tabla de APIs) y repetir unos
            # pasos por elemento; lo que extraigan se junta en una lista.
            como, juntar = arg["como"], []
            for item in datos[arg["lista"]]:
                vars_ = {f"{como}.{k}": v for k, v in item.items()}
                sub = {}
                ejecutar(page, sustituir(arg["pasos"], vars_), espera_ms, salida, traza, sub, nivel + 1)
                juntar.append({**({arg["clave"]: item[arg["clave"]]} if "clave" in arg else {}), **sub})
            datos[arg.get("a", arg["lista"] + "_detalle")] = juntar
        elif verbo == "captura":
            page.screenshot(path=str(salida / arg["a"]), full_page=True)
        else:
            raise ValueError(f"verbo desconocido: {verbo}")
        traza.append({"paso": i, "verbo": verbo, "ms": round((time.monotonic() - t0) * 1000)})
    return datos


def correr(flujo: dict, params: dict, cdp: str, espera_ms: int = 10000,
           sin_guardian: bool = False) -> tuple[bool, Path]:
    g = vigilado(cdp)
    if not g and not sin_guardian:
        raise SystemExit(f"No hay guardián vigilando {cdp}. Arráncalo (nav guardian) o "
                         "usa --sin-guardian sabiendo que nada frena una petición que modifique.")
    if g and flujo.get("modo", "lectura") == "lectura" and g["modo"] == "libre":
        raise SystemExit("El flujo es de lectura y el guardián está en modo libre: no corro.")
    for k, d in (flujo.get("parametros") or {}).items():
        if k not in params:
            if d.get("secreto") and sys.stdin.isatty():
                params[k] = getpass.getpass(f"{k}: ")
            elif "defecto" in d:
                params[k] = d["defecto"]
    pasos = sustituir(flujo["pasos"], params)
    salida = SALIDAS / flujo["nombre"] / time.strftime("%Y%m%d-%H%M%S")
    salida.mkdir(parents=True, exist_ok=True)
    # Mientras corre: quien mire (el hub) sabe que está en curso y de quién.
    import os
    (salida / "en-curso.json").write_text(json.dumps({"pid": os.getpid(), "inicio": time.time()}))
    traza = []
    publicos = {k: v for k, v in params.items() if not (flujo.get("parametros", {}).get(k) or {}).get("secreto")}
    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp(cdp).contexts[0]
        page = ctx.new_page()
        try:
            datos = ejecutar(page, pasos, espera_ms, salida, traza)
            (salida / "resultado.json").write_text(json.dumps(
                {"flujo": flujo["nombre"], "parametros": publicos, "datos": datos, "traza": traza},
                ensure_ascii=False, indent=1))
            return True, salida
        except Exception as e:
            n = len(traza) + 1
            try:
                vista = page.locator("body").aria_snapshot()[:20000]
                page.screenshot(path=str(salida / "fallo.png"))
            except Exception:
                vista = "(no se pudo leer la página)"
            (salida / "fallo.json").write_text(json.dumps(
                {"flujo": flujo["nombre"], "paso": n, "definicion": flujo["pasos"][n - 1] if n <= len(pasos) else None,
                 "error": str(e).splitlines()[0][:500], "url": page.url, "traza": traza,
                 "lo_que_se_veia": vista}, ensure_ascii=False, indent=1))
            return False, salida
        finally:
            (salida / "en-curso.json").unlink(missing_ok=True)
            try:
                page.close()
            except Exception:
                pass


def main():
    a = argparse.ArgumentParser(description="Repetir un flujo grabado")
    a.add_argument("flujo")
    a.add_argument("--cdp", default="http://127.0.0.1:9222")
    a.add_argument("-p", "--param", action="append", default=[], help="nombre=valor")
    a.add_argument("--espera", type=int, default=10000)
    a.add_argument("--sin-guardian", action="store_true")
    args = a.parse_args()
    flujo = yaml.safe_load(Path(args.flujo).read_text())
    params = dict(x.split("=", 1) for x in args.param)
    ok, salida = correr(flujo, params, args.cdp, args.espera, args.sin_guardian)
    print(("✓ " if ok else "✗ ") + str(salida / ("resultado.json" if ok else "fallo.json")))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
