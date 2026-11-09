"""`uv run python -m hub.secretario [orden]`.

    (sin orden)         el servicio (lo que corre hub-secretario)
    vuelta              una vuelta del ciclo ahora: fuentes, triaje, recordatorios…
    preguntar «texto»   le pregunta en la terminal y espera la respuesta
    telegram-entrar     conecta tu cuenta de Telegram (pide el código que te llega)
    google-entrar       conecta tu Google Calendar (un enlace para el navegador, también de otra PC)
    ical-entrar         lee tu calendario por su dirección secreta iCal (sólo lectura, sin Google Cloud)
    correo-entrar       conecta tu correo por IMAP (pide servidor, usuario y contraseña de aplicación)
    whatsapp ORDEN      WhatsApp provisional: entrar | escuchar | comprobar (colector) | comparar (lectores)
    estado              cómo está: fuentes, eventos, compromisos
    asuntos [--todos]   lo que te espera, de cada dueño en vivo (con --todos, también lo callado y lo resuelto)
    asuntos reabrir CLAVE   vuelve a sacar un asunto que callaste
    proyecto-dice PROYECTO --tipo pendiente|pregunta|aviso [--vence AAAA-MM-DD[THH:MM]] [--para yo|NOMBRE]
                  [--enlace /…] [--clave CLAVE] «texto»
                        lo que un proyecto registrado le dice al dueño: queda en la cola y el
                        secretario lo recoge en su próxima vuelta (decisión 387)
    proyecto-respuestas PROYECTO [--borrar]
                        lo que el dueño le contestó a ese proyecto, en JSON (una por línea);
                        con --borrar, quita las que acaba de leer (decisión 387)
    relevo --origen X [--enlace /…] «texto»
                        lo que sólo él puede hacer en la PC (un captcha): un asunto que se le
                        abre en la PC, nunca en el teléfono (decisión 388)
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    orden = sys.argv[1] if len(sys.argv) > 1 else "servicio"
    if orden == "servicio":
        from .servicio import correr
        correr()
    elif orden == "vuelta":
        from . import memoria, servicio
        con = memoria.conectar()
        print("eventos nuevos:", servicio.leer_fuentes(con, forzar=True))
        servicio.una_vuelta(con)
        print(json.dumps(estado(), ensure_ascii=False, indent=2))
    elif orden == "preguntar":
        preguntar(" ".join(sys.argv[2:]))
    elif orden == "telegram-entrar":
        from .fuentes.telegram import entrar
        entrar()
    elif orden == "correo-entrar":
        from .fuentes.correo import entrar
        entrar()
    elif orden == "whatsapp":
        from .fuentes.whatsapp import colector
        sys.exit(colector(sys.argv[2] if len(sys.argv) > 2 else ""))
    elif orden == "google-entrar":
        from .agenda.google import entrar
        entrar()
    elif orden == "ical-entrar":
        from .agenda.ical import entrar
        entrar()
    elif orden == "estado":
        print(json.dumps(estado(), ensure_ascii=False, indent=2))
    elif orden == "asuntos" and sys.argv[2:3] == ["reabrir"] and len(sys.argv) == 4:
        sys.exit(reabrir_asunto(sys.argv[3]))
    elif orden == "asuntos":
        sys.exit(listar_asuntos(todos="--todos" in sys.argv[2:]))
    elif orden == "proyecto-dice":
        sys.exit(proyecto_dice(sys.argv[2:]))
    elif orden == "proyecto-respuestas":
        sys.exit(proyecto_respuestas(sys.argv[2:]))
    elif orden == "relevo":
        sys.exit(relevo(sys.argv[2:]))
    else:
        print(__doc__)
        sys.exit(2)


def estado() -> dict:
    from . import memoria, piezas
    con = memoria.conectar()
    return {
        "fuentes": [f | {"cursor": None} for f in memoria.estados_fuentes(con).values()],
        **memoria.cuentas_triaje(con),
        "agenda": _agenda_disponible(),
        "avisos": _avisos_disponible(),
        "notas": con.execute("SELECT COUNT(*) FROM nota").fetchone()[0],
        "compromisos_abiertos": con.execute("SELECT COUNT(*) FROM compromiso WHERE estado = 'abierto'").fetchone()[0],
        "disponibles": {k: f.disponible() or "lista" for k, f in piezas.fuentes().items()},
    }


def listar_asuntos(todos: bool = False) -> int:
    """Lo mismo que lee su pantalla (380). Sólo lee: no marca nada como visto."""
    from . import asuntos, memoria
    con = memoria.conectar()
    try:
        r = asuntos.reunir(con, todos=todos)
    finally:
        con.close()
    for a in r.asuntos:
        print(f"[{a.estado}] {a.clase:<11} {a.texto}" + (f"  → {a.enlace}" if a.enlace else ""))
        print(f"    {a.clave}")
    if not r.asuntos:
        print("Nada te espera.")
    for f in r.fallos:
        print(f"⚠ {f}", file=sys.stderr)
    return 1 if r.fallos else 0


def reabrir_asunto(clave: str) -> int:
    """Callar es reversible sólo por él (379): esto es él, en su terminal."""
    from . import asuntos, memoria
    con = memoria.conectar()
    try:
        asuntos.reabrir(con, clave)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        con.close()
    print(f"{clave}: vuelve a salir (como vista).")
    return 0


def proyecto_dice(args: list[str]) -> int:
    """Lo que usa el operador de un proyecto para hablarle al dueño (387): deja
    el mensaje en la cola y no abre la memoria del secretario, que es de
    `hub-secretario`. El formato está en `de_proyectos`."""
    import argparse

    from .. import registry
    from . import de_proyectos, memoria
    p = argparse.ArgumentParser(prog="python -m hub.secretario proyecto-dice",
                                description="Lo que un proyecto registrado le dice al dueño, por el secretario.")
    p.add_argument("proyecto", help="el id del proyecto en el registro del hub")
    p.add_argument("--tipo", required=True, choices=de_proyectos.TIPOS)
    p.add_argument("--vence", help="sólo en un pendiente: AAAA-MM-DD[THH:MM], hora de la casa")
    p.add_argument("--para", default="yo", help="sólo en un pendiente, quién lo hace: yo (el dueño) o el nombre "
                                                "de otra persona (sigue siendo del dueño, que lo coordina)")
    p.add_argument("--enlace", default="", help="sólo en una pregunta o un aviso: una ruta del hub, p. ej. /proyecto/<id>")
    p.add_argument("--clave", default="", help="su identidad: con la misma no se apunta dos veces")
    p.add_argument("texto", nargs="+")
    a = p.parse_args(args)
    try:
        ruta = de_proyectos.dejar(a.proyecto, a.tipo, " ".join(a.texto), vence=a.vence, para=a.para,
                                  enlace=a.enlace, clave=a.clave)
    except (ValueError, registry.YamlInvalido) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Dejado en {ruta}.")
    # La cola ya existe, así que mirar si hay secretario no crea nada.
    if memoria.existe():
        print("El secretario lo recoge en su próxima vuelta (cada 30 s, si hub-secretario está en marcha).")
    else:
        print("El secretario no está instalado: esperará en la cola hasta que lo esté.")
    return 0


def proyecto_respuestas(args: list[str]) -> int:
    """La vuelta de `proyecto-dice` (387): lo que el dueño contestó en sus
    asuntos a ese proyecto, un JSON por línea (`clave`, `asunto`, `pregunta`,
    `respuesta`, `cuando`). No abre la memoria del secretario."""
    import argparse

    from .. import registry
    from . import de_proyectos
    p = argparse.ArgumentParser(prog="python -m hub.secretario proyecto-respuestas",
                                description="Lo que el dueño le contestó a un proyecto registrado.")
    p.add_argument("proyecto", help="el id del proyecto en el registro del hub")
    p.add_argument("--borrar", action="store_true", help="quita las respuestas que acaba de leer")
    a = p.parse_args(args)
    try:
        lista = de_proyectos.respuestas(a.proyecto, borrar=a.borrar)
    except (ValueError, OSError, registry.YamlInvalido) as exc:
        print(exc, file=sys.stderr)
        return 2
    for r in lista:
        print(json.dumps(r, ensure_ascii=False))
    return 0


def relevo(args: list[str]) -> int:
    """Lo que sólo el dueño puede hacer en la PC (388): un asunto `relevo` que
    se le abre en la PC por el agente de Reuniones. Nunca va al teléfono."""
    import argparse

    from . import asuntos, memoria
    p = argparse.ArgumentParser(prog="python -m hub.secretario relevo",
                                description="Lo que sólo el dueño puede hacer en su PC, en sus asuntos.")
    p.add_argument("--origen", required=True, help="quién lo pide: el navegador, una sesión…")
    p.add_argument("--enlace", default="", help="una ruta del hub")
    p.add_argument("texto", nargs="+")
    a = p.parse_args(args)
    con = memoria.conectar()
    try:
        i = asuntos.pedir_relevo(con, " ".join(a.texto), origen=a.origen, enlace=a.enlace)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        con.close()
    print(f"Relevo {i} en sus asuntos (/secretario?p=pendientes).")
    return 0


def _agenda_disponible() -> str:
    from . import agenda
    try:
        return agenda.disponible() or f"lista ({agenda.actual().nombre})"
    except LookupError as exc:
        return str(exc)


def _avisos_disponible() -> str:
    from . import avisos
    try:
        c = avisos.actual()
    except LookupError as exc:
        return str(exc)
    return c.disponible() or f"listo ({c.nombre})"


def preguntar(texto: str) -> None:
    """Lo mismo que la pantalla, en la terminal: deja el turno y lo contesta aquí."""
    from . import conversacion, memoria
    con = memoria.conectar()
    t = conversacion.recibir(con, texto)
    turno = con.execute("SELECT * FROM turno WHERE id = ?", (t["turno"],)).fetchone()
    conversacion.contestar(con, turno)
    for r in conversacion.turnos(con, t["hilo"], t["turno"]):
        print(f"[{r['modelo']} · {r['segundos']} s]\n{r['texto']}")
        for tj in r["tarjetas"]:
            print(f"\n▣ {tj['titulo']}")
            for fila in tj["filas"]:
                print("  · " + " | ".join(fila))


if __name__ == "__main__":
    main()
