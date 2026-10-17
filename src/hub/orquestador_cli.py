"""Las manos del orquestador. Todo lo que puede hacer en el mundo, y nada más.

🔴 **Este archivo ES su contrato de acción.** Cada subcomando amplía lo que un
agente sin nadie delante puede hacer, así que la lista es corta y cada orden
comprueba sus permisos aquí —en código que él no puede editar— y no en su
prompt (decisión 256). Lo que no hay, a propósito:

- **Nada que escriba en un proyecto.** Le pide el trabajo a la sesión del
  proyecto; el hub sigue sin escribir fuera de su casa.
- **Nada que cambie permisos.** Los concede el dueño en la web; aquí sólo se leen.
- **Nada que mande a Telegram.** Deja el timbre y el relé —el único con el
  token, regla dura 22— lo toca.
- **Nada que borre.** Principio 9.

    orq tarea                     la tarea en curso, entera
    orq proyectos                 a qué proyectos llega y con qué nivel
    orq sesiones <proyecto>       las sesiones de un agente abiertas ahí
    orq abrir <proyecto> [--nombre N]   abre una, sólo si no hay ninguna
    orq mandar <proyecto> <pane>  le manda trabajo (el texto por stdin)
    orq respuesta <pane> [--n N]  lo que contestó a tu último mensaje
    orq plan                      guarda el plan (por stdin), con pasos numerados
    orq paso <n>                  en qué paso vas; los de antes quedan hechos
    orq avance "<texto>"          cómo va, en una línea, para el dueño
    orq preguntar "<texto>"       a la bandeja del dueño; la tarea espera
    orq terminar "<resumen>"      cierra la tarea
"""

from __future__ import annotations

import argparse
import sys

from . import config, db, intercambio, orquestador


def _texto(args_texto: str | None) -> str:
    """El texto del argumento, o de stdin si no hay. Largo va por stdin."""
    if args_texto and args_texto != "-":
        return args_texto
    return sys.stdin.read()


def cmd_tarea(con, args) -> int:
    t = orquestador.exigir_viva()
    print(f"# Tarea {t['id']} — {orquestador.ETIQUETA[t['estado']]}\n")
    print("## Lo que pidió el dueño\n")
    print(t["pedido"] + "\n")
    plan = orquestador.plan(t["id"])
    print("## Tu plan\n")
    print((plan or "(todavía no hay: escríbelo con `./orq plan`)") + "\n")
    if t.get("pasos"):
        print(f"## Paso {t.get('paso') or 1} de {t['pasos']}\n")
    if t.get("avance"):
        print(f"## Último avance\n\n{t['avance']}\n")
    if t.get("pregunta"):
        print(f"## Pregunta abierta al dueño\n\n{t['pregunta']['texto']}\n")
    abiertas = [e for e in t["esperas"] if e["estado"] == "esperando"]
    if abiertas:
        print("## Esperando a\n")
        for e in abiertas:
            que = "que quede libre" if e["tipo"] == "libre" else f"respuesta al #{e['id']}"
            print(f"- {e['proyecto']} ({e['pane_id']}): {que}, desde {e['enviado']}")
        print()
    print("## Bitácora (lo último)\n")
    for linea in orquestador.bitacora(t["id"])[-25:]:
        donde = f" [{linea['proyecto']} {linea.get('pane_id', '')}]" if linea.get("proyecto") else ""
        texto = " ".join(str(linea.get("texto", "")).split())
        print(f"- {linea['cuando'][11:16]} {linea['tipo']}{donde}: {texto[:300]}")
    print("\n## Alcance\n")
    _proyectos(con, solo_con_alcance=True)
    print(f"\nIntercambio (para dejarle archivos al dueño): {intercambio.carpeta()}/")
    return 0


def _proyectos(con, solo_con_alcance: bool) -> None:
    filas = con.execute(
        "SELECT id, nombre, asiento FROM proyecto WHERE status != 'archivado' "
        "AND tipo = 'proyecto' ORDER BY id").fetchall()
    alguno = False
    for f in filas:
        nivel = orquestador.nivel_de(con, f["id"])
        if solo_con_alcance and nivel == "nada":
            continue
        alguno = True
        print(f"- {f['id']} ({f['nombre']}): {nivel} — {f['asiento'] or 'sin asiento'}")
    if not alguno:
        print("- ninguno: el dueño no te ha dado alcance sobre ningún proyecto todavía")


def cmd_proyectos(con, args) -> int:
    print("Niveles:")
    for n in orquestador.NIVELES:
        print(f"  {n}: {orquestador.DESCRIPCION[n]}")
    print()
    _proyectos(con, solo_con_alcance=False)
    return 0


def cmd_sesiones(con, args) -> int:
    orquestador.exigir_viva()
    orquestador.exigir(con, args.proyecto)
    vivas = orquestador.sesiones(con, args.proyecto)
    if not vivas:
        print(f"«{args.proyecto}» no tiene ninguna sesión abierta. "
              f"Ábrela con `./orq abrir {args.proyecto}`.")
        return 0
    for s in vivas:
        estado = "trabajando" if s["trabajando"] else "libre"
        print(f"- {s['pane_id']}  {s['agente']}  {estado}  {s['nombre']}")
        f = orquestador.ficha(s["pane_id"])
        contexto = f"{f['contexto'] // 1000}k tokens" if f["contexto"] is not None else "no se pudo leer"
        print(f"    modelo: {f['modelo'] or 'el predeterminado (no se ve cuál)'}"
              f" · esfuerzo: {f['esfuerzo'] or 'por omisión'}"
              f" · contexto: {contexto}"
              f" · compacta sola al {f['compacta_al'] + ' %' if f['compacta_al'] else 'borde (por omisión)'}")
    if len(vivas) > 1:
        print("\nHay varias: si no sabes a cuál mandar, pregúntale al dueño.")
    return 0


def cmd_abrir(con, args) -> int:
    r = orquestador.abrir_sesion(con, args.proyecto, args.nombre, args.modelo, args.esfuerzo)
    print(f"Abierta en {r['pane_id']}" + ("" if r["listo"] else
          " (todavía arrancando: si `mandar` dice que no está lista, espera un momento)"))
    return 0


def cmd_mandar(con, args) -> int:
    r = orquestador.mandar(con, args.proyecto, args.pane, _texto(args.texto))
    if not r["enviado"]:
        if r.get("necesita_al_dueno"):
            print(f"No se mandó: {r['motivo']}. Esto NO se arregla esperando: ya se "
                  "avisó al dueño. Díselo también con `./orq avance` (qué sesión y "
                  "qué tiene que contestar) y termina tu turno: te despierto cuando "
                  "quede libre.")
            return 0
        print(f"No se mandó: {r['motivo']}. Te despierto cuando quede libre; "
              "termina tu turno.")
        return 0
    extra = "" if r["confirmado"] else (
        " (escrito, pero no se pudo confirmar que saliera: NO lo repitas;"
        " si no hay respuesta, pregúntale al dueño)")
    print(f"Mandado (#{r['espera']}){extra}. Termina tu turno: te despierto cuando acabe.")
    return 0


def cmd_ajustar(con, args) -> int:
    r = orquestador.ajustar(con, args.proyecto, args.pane, args.modelo, args.esfuerzo, args.forzar)
    print(f"Ajustada: {r['cambio']}. Conserva su conversación." + ("" if r["listo"] else
          " Todavía arrancando: termina tu turno, te despierto cuando quede libre."))
    return 0


def cmd_compactar(con, args) -> int:
    orquestador.compactar(con, args.proyecto, args.pane, args.foco)
    print("Compactando. Termina tu turno: te despierto cuando quede libre.")
    return 0


def cmd_respuesta(con, args) -> int:
    r = orquestador.respuesta(args.pane, args.n)
    if r["origen"] == "pantalla":
        print("(No encontré la conversación en el transcript: esto es lo que se ve "
              "en su pantalla, y puede estar incompleto.)\n")
    if not r["terminada"]:
        print("(Todavía no ha terminado: esto es lo que lleva.)\n")
    print(r["texto"] or "(sin respuesta todavía)")
    return 0


def cmd_plan(con, args) -> int:
    orquestador.fijar_plan(_texto(None))
    print("Plan guardado. El dueño lo ve en el hub.")
    return 0


def cmd_paso(con, args) -> int:
    orquestador.marcar_paso(args.n)
    print(f"Paso {args.n}.")
    return 0


def cmd_avance(con, args) -> int:
    orquestador.avance(args.texto)
    print("Anotado.")
    return 0


def cmd_preguntar(con, args) -> int:
    orquestador.preguntar(_texto(args.texto))
    print("Pregunta en su bandeja. Termina tu turno: te despierto con su respuesta.")
    return 0


def cmd_terminar(con, args) -> int:
    orquestador.terminar(_texto(args.texto))
    print("Tarea cerrada. El dueño recibe el aviso.")
    return 0


ORDENES = {
    "tarea": cmd_tarea,
    "proyectos": cmd_proyectos,
    "sesiones": cmd_sesiones,
    "abrir": cmd_abrir,
    "mandar": cmd_mandar,
    "ajustar": cmd_ajustar,
    "compactar": cmd_compactar,
    "respuesta": cmd_respuesta,
    "plan": cmd_plan,
    "paso": cmd_paso,
    "avance": cmd_avance,
    "preguntar": cmd_preguntar,
    "terminar": cmd_terminar,
}


def construir_parser() -> argparse.ArgumentParser:
    partes = argparse.ArgumentParser(
        prog="orq", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = partes.add_subparsers(dest="orden", required=True)
    sub.add_parser("tarea")
    sub.add_parser("proyectos")
    p = sub.add_parser("sesiones")
    p.add_argument("proyecto")
    p = sub.add_parser("abrir")
    p.add_argument("proyecto")
    p.add_argument("--nombre", default="")
    p.add_argument("--modelo", default="")
    p.add_argument("--esfuerzo", default="")
    p = sub.add_parser("ajustar")
    p.add_argument("proyecto")
    p.add_argument("pane")
    p.add_argument("--modelo", default="")
    p.add_argument("--esfuerzo", default="")
    p.add_argument("--forzar", action="store_true")
    p = sub.add_parser("compactar")
    p.add_argument("proyecto")
    p.add_argument("pane")
    p.add_argument("foco", nargs="?", default="")
    p = sub.add_parser("mandar")
    p.add_argument("proyecto")
    p.add_argument("pane")
    p.add_argument("texto", nargs="?", default=None)
    p = sub.add_parser("respuesta")
    p.add_argument("pane")
    p.add_argument("--n", type=int, default=None)
    sub.add_parser("plan")
    p = sub.add_parser("paso")
    p.add_argument("n", type=int)
    p = sub.add_parser("avance")
    p.add_argument("texto")
    p = sub.add_parser("preguntar")
    p.add_argument("texto", nargs="?", default=None)
    p = sub.add_parser("terminar")
    p.add_argument("texto", nargs="?", default=None)
    return partes


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    try:
        codigo = ORDENES[args.orden](con, args)
        con.commit()
        return codigo
    except (orquestador.TareaCerrada, orquestador.SinPermiso, ValueError, RuntimeError) as exc:
        # Al stderr y con código de error, pero legible: quien lo lee es un
        # modelo que tiene que entender qué no pudo hacer y por qué.
        print(f"orq: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
