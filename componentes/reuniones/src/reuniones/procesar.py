"""Procesar una reunión grabada: transcribir, juntar con las capturas y resumir.

Por etapas, y cada una deja su archivo: si el resumen falla (sin red, sin
cuota) la transcripción ya está y no se repite. `procesado.json` dice en qué
etapa va, para que el hub lo enseñe mientras corre.
"""
import argparse
import sys
import time
from pathlib import Path

from . import carpeta, resumir, transcribir, voces


def _estado(c: Path, **cambios):
    e = carpeta.leer(c / "procesado.json") or {"etapas": {}}
    for k, v in cambios.items():
        if k == "etapa":
            e["etapas"][v[0]] = v[1]
        else:
            e[k] = v
    carpeta.escribir(c / "procesado.json", e)


def fotos(c: Path) -> list[dict]:
    d = c / "fotos"
    out = []
    for f in sorted(d.glob("*.jpg")) if d.is_dir() else []:
        try:
            out.append({"t": int(f.stem), "archivo": f.name})
        except ValueError:
            continue
    return out


def markdown(segs: list[dict], fts: list[dict], meta: dict) -> str:
    """La transcripción para leer (y para Claude), con las capturas intercaladas."""
    lineas = [f"# Reunión {meta.get('id', '')}", ""]
    if meta.get("proceso"):
        lineas.append(f"Aplicación: {meta['proceso'].get('nombre', '')}  ")
    lineas.append("")
    eventos = [(s["ini"], 1, s) for s in segs] + [(f["t"], 0, f) for f in fts]
    for t, tipo, x in sorted(eventos, key=lambda e: (e[0], e[1])):
        if tipo == 0:
            lineas.append(f"📷 [{carpeta.hhmmss(t)}] cambió la pantalla ({x['archivo']})")
        else:
            lineas.append(f"[{carpeta.hhmmss(t)}] **{x['quien']}:** {x['texto']}")
    return "\n".join(lineas) + "\n"


def resumen_md(r: dict) -> str:
    l = [f"# {r.get('titulo') or 'Reunión'}", "", r.get("resumen", ""), ""]
    for clave, titulo in (("decisiones", "Decisiones"), ("para_mi", "Para mí"),
                          ("preguntas_abiertas", "Preguntas abiertas")):
        if r.get(clave):
            l += [f"## {titulo}", *[f"- {x}" for x in r[clave]], ""]
    if r.get("tareas"):
        l += ["## Tareas", *[f"- **{t.get('quien', '')}**: {t.get('que', '')}"
                              + (f" ({t['cuando']})" if t.get("cuando") else "") for t in r["tareas"]], ""]
    if r.get("momentos"):
        l += ["## Momentos", *[f"- {m.get('t', '')} — {m.get('que', '')}" for m in r["momentos"]], ""]
    return "\n".join(l)


def procesar(c: Path, resumen: bool = True, separar: bool = True) -> dict:
    meta = carpeta.leer(c / "meta.json") or {"id": c.name}
    _estado(c, inicio=time.time(), estado="procesando", error=None)
    try:
        if not (c / "transcripcion.json").exists():
            _estado(c, etapa=("transcribir", "en-curso"))
            t0 = time.time()
            from .comprimir import audio
            vacia = c / "no-existe.wav"
            segs = transcribir.fusionar(transcribir.pista(audio(c, "reunion") or vacia),
                                        transcribir.pista(audio(c, "micro") or vacia))
            carpeta.escribir(c / "transcripcion.json", segs)
            _estado(c, etapa=("transcribir", f"hecho en {time.time() - t0:.0f} s"))
        segs = carpeta.leer(c / "transcripcion.json") or []
        # Las voces de la reunión, una vez: si ya hay «Persona N», está hecho.
        # Si no se puede (sin token, sin modelo), se sigue con «Reunión» y se
        # dice: separar voces mejora el resumen, no es lo que lo hace posible.
        if separar and segs and not any(str(s.get("quien", "")).startswith("Persona ") for s in segs):
            _estado(c, etapa=("voces", "en-curso"))
            transcribir.soltar_modelo()   # Whisper fuera de la GPU antes de pyannote
            try:
                t0 = time.time()
                segs = voces.separar(c)
                n = len({s["quien"] for s in segs if s["quien"].startswith("Persona ")})
                _estado(c, etapa=("voces", f"{n} voces en {time.time() - t0:.0f} s"))
            except voces.SinSeparar as e:
                _estado(c, etapa=("voces", f"sin separar: {e}"))
        segs = voces.con_nombres(segs, voces.nombres(c))
        md = markdown(segs, fotos(c), meta)
        (c / "transcripcion.md").write_text(md, encoding="utf-8")
        if resumen and not (c / "resumen.json").exists():
            _estado(c, etapa=("resumir", "en-curso"))
            r = resumir.con_claude(md)
            carpeta.escribir(c / "resumen.json", r)
            (c / "resumen.md").write_text(resumen_md(r), encoding="utf-8")
            _estado(c, etapa=("resumir", "hecho"))
        _estado(c, estado="hecho", fin=time.time())
    except Exception as e:
        _estado(c, estado="fallo", error=str(e)[:500], fin=time.time())
        raise
    return carpeta.leer(c / "procesado.json")


def main():
    a = argparse.ArgumentParser(prog="reuniones")
    sub = a.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("procesar"); p.add_argument("id"); p.add_argument("--sin-resumen", action="store_true")
    p.add_argument("--rehacer", action="store_true", help="borra lo procesado y empieza de cero")
    sub.add_parser("listar")
    p = sub.add_parser("voces", help="separa las voces de una reunión ya transcrita")
    p.add_argument("id"); p.add_argument("--resumen", action="store_true", help="y rehace el resumen")
    p = sub.add_parser("nombres", help='pone nombre a las voces: "Persona 1=Ana"')
    p.add_argument("id"); p.add_argument("pares", nargs="*")
    p.add_argument("--resumen", action="store_true", help="y rehace el resumen con los nombres")
    p = sub.add_parser("comprimir"); p.add_argument("ids", nargs="+")
    args = a.parse_args()
    if args.cmd == "comprimir":
        from . import comprimir
        fallos = 0
        for id_ in args.ids:
            c = carpeta.de(id_)
            marca = c / "comprimiendo"
            marca.touch()
            try:
                r = comprimir.comprimir(c)
                print(f"✓ {id_}: {r['antes'] / 1e6:.0f} MB → {r['despues'] / 1e6:.0f} MB")
            except Exception as e:
                fallos += 1
                carpeta.escribir(c / "comprimido.json", {"error": str(e)[:300], "fecha": time.time()})
                print(f"✗ {id_}: {e}")
            finally:
                marca.unlink(missing_ok=True)
        sys.exit(1 if fallos else 0)
    if args.cmd == "listar":
        for d in sorted(carpeta.raiz().glob("*"), reverse=True):
            if carpeta.ID.match(d.name):
                e = (carpeta.leer(d / "procesado.json") or {}).get("estado", "sin procesar")
                print(f"{d.name}  {e}")
        return
    c = carpeta.de(args.id) if carpeta.ID.match(args.id) else Path(args.id)
    if args.cmd in ("voces", "nombres"):
        if args.cmd == "voces":
            # Volver a separar: se parte de «Reunión» otra vez.
            segs = carpeta.leer(c / "transcripcion.json") or []
            carpeta.escribir(c / "transcripcion.json",
                             [{**x, "quien": "Yo" if x.get("quien") == "Yo" else "Reunión"} for x in segs])
        else:
            voces.poner_nombres(c, dict(par.split("=", 1) for par in args.pares if "=" in par))
        if args.resumen:
            for n in ("resumen.json", "resumen.md"):
                (c / n).unlink(missing_ok=True)
        try:
            e = procesar(c, resumen=True, separar=args.cmd == "voces")
        except Exception as exc:
            sys.exit(f"✗ {exc}")
        print(f"✓ {c}  {e.get('etapas')}")
        return
    if args.rehacer:
        for n in ("transcripcion.json", "transcripcion.md", "resumen.json", "resumen.md", "procesado.json"):
            (c / n).unlink(missing_ok=True)
    try:
        e = procesar(c, resumen=not args.sin_resumen)
    except Exception as exc:
        sys.exit(f"✗ {exc}")
    print(f"✓ {c}  {e.get('etapas')}")
