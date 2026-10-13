"""Las manos del agente entrevistador. Todo lo que puede hacer, y nada más.

🔴 **Este archivo ES el contrato de la decisión f9.** El agente que habla con la
persona no construye y no puede aunque quiera: su única salida es la ficha, y su
única forma de hablar es encolar un mensaje que manda otro proceso. Cada
subcomando que se añada aquí amplía lo que ese agente puede hacer en el mundo, y
por eso la lista es corta y cada uno tiene su motivo escrito.

Lo que **no** hay, y no es un olvido:

- **No manda nada.** Encola, y el relé —el único que tiene el token, regla dura
  22— es quien manda. Un agente con el token sería un agente que puede escribir
  a cualquiera.
- **No despliega, no toca git, no abre puertos.** El gate humano va antes de
  gastar (decisión n7); si el agente pudiera construir, ese gate ya no
  significaría nada porque el gasto habría empezado antes de la aprobación.
- **No borra un encargo.** Borrar es de quien lo encargó, y el hub no poda nada
  solo (principio 9).

Se usa así, desde el panel del agente:

    encargo ficha                     qué sé, qué falta y qué toca preguntar
    encargo preguntar                 hace la siguiente pregunta que toque
    encargo responde <fase> "<texto>" aterriza una respuesta en su casilla
    encargo anota "<texto>"           guarda lo que contó, aunque no toque
    encargo decir "<texto>"           le dice algo con tus palabras
    encargo muestras [estilos|pantallas]   le manda el catálogo para que elija
    encargo mirar [url]               pinta lo construido (o una URL local) para poder juzgarlo
    encargo quitar <archivo>          borra un archivo del sitio o de la app, y sólo de ahí
    encargo servir                    arranca la app en local con una base de prueba
    encargo parar                     apaga la app que arrancó `servir`
    encargo deshacer [n]              retira lo que encolaste y aún no ha salido
    encargo rendirse <fase>           agotado el tope, el hueco se declara
    encargo nombrar <id>              apunta el nombre que ella quiere (se aplica al publicar)
    encargo proponer <archivo.md>     cierra la ficha y manda el plan al dueño
    encargo listo                     lo construido está; avisa a quien aprobó
    encargo publicado <url>           apunta la URL y se la manda a los dos
    encargo conversacion              lo hablado hasta ahora, en orden

Las dos últimas sólo funcionan en su momento del ciclo —`listo` mientras se
construye, `publicado` después—, así que el entrevistador no las alcanza aunque
las escriba: el estado del encargo es parte del contrato, no sólo un dato.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import buzon, config, db, encargos, estilos, mirar

# Cuántas muestras van en una tanda. Más de esto y la persona deja de comparar y
# empieza a elegir la última que vio; en un móvil, además, seis fotos seguidas
# ya son un muro. El catálogo entero se enseña en dos tandas si hace falta.
POR_TANDA = 6


def _salir(mensaje: str) -> int:
    print(mensaje, file=sys.stderr)
    return 2


def _encargo_actual(con: sqlite3.Connection, dado: str = "") -> str:
    """Contra qué encargo se trabaja. Con uno solo abierto no hay que decirlo.

    El agente corre dentro de la carpeta de su encargo, así que el caso normal
    es que no haya ambigüedad. Pedirle el id en cada orden sería ceremonia, y la
    ceremonia en una TUI acaba en un id copiado mal.
    """
    if dado:
        return dado
    desde_la_carpeta = Path.cwd().name
    if encargos.ver(con, desde_la_carpeta):
        return desde_la_carpeta
    abiertos = [e for e in encargos.listar(con)
                if e["estado"] not in ("publicado", "descartado")]
    if len(abiertos) == 1:
        return abiertos[0]["id"]
    raise SystemExit(_salir(
        "hay varios encargos abiertos: di cuál con --encargo. "
        f"Son: {', '.join(e['id'] for e in abiertos) or 'ninguno'}"
    ))


# --------------------------------------------------------------------------- #
# Mirar
# --------------------------------------------------------------------------- #


def texto_de_la_ficha(con: sqlite3.Connection, encargo_id: str) -> str:
    """Qué se sabe, qué falta y qué toca. Es el «dónde estoy» del agente.

    🔴 Esto es lo que hace **inofensivo compactar**. El estado de la entrevista
    no vive en la conversación: vive en la ficha, y se puede volver a leer
    entero en cualquier momento. Un agente recién reiniciado que ejecute esto
    sabe exactamente lo mismo que uno que lleva media hora hablando.
    """
    fila = encargos.ver(con, encargo_id)
    if not fila:
        return f"no hay ningún encargo «{encargo_id}»"
    ficha = encargos.cargar_ficha(con, encargo_id)
    persona = encargos.ver_persona(con, int(fila["user_id"]))

    lineas = [
        f"encargo   {encargo_id}   ({fila['estado']}, ronda {fila['ronda']})",
        f"hablas con {encargos.nombre_visible(persona)}",
        "",
        "LO QUE YA SÉ",
    ]
    if not ficha.campos:
        lineas.append("  — todavía nada")
    for fase in encargos.FASES:
        valor = ficha.campos.get(fase.campo)
        if not valor:
            continue
        marca = "«no lo sabe»" if valor == encargos.NO_LO_SABE else valor
        lineas.append(f"  {fase.id:8} {marca}")

    lineas += ["", "LO QUE FALTA"]
    pendientes = [f for f in encargos.FASES if not ficha.cerrada(f.id)]
    if not pendientes:
        lineas.append("  — nada: la ficha está completa")
    for fase in pendientes:
        veces = ficha.preguntado.get(fase.id, 0)
        aviso = f"  (preguntado {veces} de {encargos.TOPE_POR_FASE})" if veces else ""
        lineas.append(f"  {fase.id:8} {fase.titulo}{aviso}")

    siguiente = ficha.siguiente()
    lineas += ["", "QUÉ TOCA AHORA"]
    if siguiente and siguiente.id == "alcance":
        lineas += [
            "  🔴 su VISTO BUENO. Dile con sus palabras qué pantallas tendría su sistema",
            "  y para qué sirve cada una (tres o cuatro suelen bastar), y pregúntale:",
            "  «¿lo mandamos así para que lo veas, o quieres contarme más antes?». Si",
            "  cuenta más, anótalo y vuelve a preguntar. Sólo cuando diga que va:",
            "  encargo responde alcance \"<lo que dijo>\"",
        ]
    elif siguiente:
        lineas.append(f"  fase «{siguiente.id}»: {siguiente.pregunta}")
        if siguiente.se_elige:
            lineas.append("  🔴 esta se contesta ELIGIENDO: escribe primero `bosquejo.html` (SU "
                          "pantalla, con sus palabras) y luego `encargo muestras`. No preguntes.")
    elif fila["estado"] == "recogiendo" and int(fila["ronda"] or 1) > 1:
        lineas.append(
            f"  es la ronda {fila['ronda']}: ella ya vio lo publicado. Lo que toca es lo "
            "que pidió (la cola y `encargo conversacion`), preguntar sólo lo que falte "
            "para hacerlo, y `encargo proponer` con ese cambio.")
    elif fila["estado"] == "recogiendo":
        lineas.append("  tienes suficiente. Confirma con ella y luego `encargo proponer`.")
    else:
        lineas.append(f"  nada por preguntar; el encargo está en «{fila['estado']}».")

    if ficha.dicho:
        lineas += ["", f"LO QUE CONTÓ ({len(ficha.dicho)} apuntes; nada se tira)"]
        for apunte in ficha.dicho[-5:]:
            lineas.append(f"  · {apunte['texto'][:120]}")

    esperando = buzon.en_cola(con, encargo_id)
    if esperando:
        lineas += ["", f"🔴 hay {len(esperando)} mensaje(s) sin leer todavía en la cola"]
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
# Hacer
# --------------------------------------------------------------------------- #


def cmd_ficha(con, args) -> int:
    print(texto_de_la_ficha(con, _encargo_actual(con, args.encargo)))
    return 0


def cmd_preguntar(con, args) -> int:
    """La siguiente pregunta que toque, encolada y contada.

    Contar es lo que hace que el tope exista (decisión f8): quien no sabe algo
    no lo va a saber a la quinta pregunta, e insistir es la forma más rápida de
    que alguien deje de contestar.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    ficha = encargos.cargar_ficha(con, encargo_id)
    fase = ficha.siguiente()
    if not fase:
        return _salir("no queda ninguna fase abierta: la ficha ya está completa")
    if fase.se_elige:
        return _salir(
            f"la fase «{fase.id}» se contesta eligiendo, no preguntando. "
            "Usa `encargo muestras`."
        )
    texto = args.texto or ficha.preguntar(fase.id)
    if args.texto:
        ficha.preguntar(fase.id)      # cuenta igual: lo que se mide es insistir
    encargos.guardar_ficha(con, ficha)
    buzon.encolar_salida(con, encargo_id, texto)
    print(f"encolada la pregunta de la fase «{fase.id}»:\n  {texto}")
    return 0


def cmd_responde(con, args) -> int:
    encargo_id = _encargo_actual(con, args.encargo)
    ficha = encargos.cargar_ficha(con, encargo_id)
    texto = args.texto

    # 🔴 Una fase que se elige guarda el **id de lo elegido**, no la frase.
    # Salió del primer ensayo con un agente de verdad: guardó «Cálido, como una
    # tienda de barrio» —el nombre de la muestra, que es lo que se le enseñó— y
    # el constructor, que busca un id, se quedó sin saber qué eligió y construyó
    # con el de referencia. La única decisión que ella pudo tomar viendo,
    # descartada en silencio. Aquí se resuelve, y si no se puede **no se
    # adivina**: se dice y se vuelve a preguntar.
    fase = encargos.POR_ID.get(args.fase)
    if fase and fase.se_elige:
        elegido = estilos.identificar(texto, "estilos")
        if not elegido:
            return _salir(
                f"no se sabe cuál de las muestras es «{texto}». Guárdalo con su "
                f"id —{', '.join(e.id for e in estilos.ESTILOS)}— o vuelve a "
                "preguntarle cuál. Construir con el estilo equivocado es peor "
                "que preguntar otra vez."
            )
        # Lo que dijo no se pierde: va a `dicho`, que es donde no se tira nada.
        ficha.anota(texto, args.fase)
        texto = elegido

    try:
        ficha.responde(args.fase, texto)
    except ValueError as exc:
        return _salir(str(exc))
    if texto == args.texto:
        ficha.anota(args.texto, args.fase)
    encargos.guardar_ficha(con, ficha)
    print(texto_de_la_ficha(con, encargo_id))
    return 0


def cmd_anota(con, args) -> int:
    """Lo que contó y no cabía en ninguna casilla. Nada se tira (decisión f10)."""
    encargo_id = _encargo_actual(con, args.encargo)
    ficha = encargos.cargar_ficha(con, encargo_id)
    ficha.anota(args.texto, args.fase or "")
    encargos.guardar_ficha(con, ficha)
    print(f"apuntado ({len(ficha.dicho)} en total)")
    return 0


def cmd_decir(con, args) -> int:
    encargo_id = _encargo_actual(con, args.encargo)
    fila = encargos.ver(con, encargo_id)
    if fila and fila["estado"] == "propuesta":
        # Valla, no consejo: tras `proponer` el hub ya le dijo que está en
        # revisión, y dos agentes seguidos se lo repitieron igual con esta
        # orden. Dos avisos por lo mismo se leen como ruido.
        return _salir("el plan ya está mandado y a ella ya se le dijo que está en "
                      "revisión: no hay nada más que decirle hasta que se decida")
    buzon.encolar_salida(con, encargo_id, args.texto)
    print("encolado; lo manda el relé en la siguiente vuelta")
    return 0


# Lo que se le dice ANTES de las fotos, y lo dice la orden y no el agente
# (decisión 230). La primera persona real recibió seis imágenes detrás de una
# pregunta sobre su negocio y «no sabía ni que estaba eligiendo»: un cambio de
# tema sin aviso se lee como un salto. Esto lo anuncia y dice qué son las fotos
# —el aire, no su negocio— y cómo contestar: por el número.
PRESENTACION = {
    "estilos": (
        "Ahora algo distinto, y es lo último de esta parte: te mando seis "
        "imágenes de cómo podría verse lo tuyo. Todavía no son de tu negocio, "
        "son sólo el aire: los colores, la letra, el orden. Dime cuál te gusta "
        "más, con el número."
    ),
    "pantallas": (
        "Te mando unas pantallas de ejemplo, con el mismo aire todas. Dime "
        "cuál se parece más a lo que te serviría, con el número."
    ),
    "bosquejo": (
        "Ahora algo distinto, y es lo último de esta parte: te mando seis "
        "versiones de un boceto de tu pantalla, hecho con lo que me contaste. "
        "No es la página todavía; es para elegir el aire: los colores, la "
        "letra, el orden. Dime cuál te gusta más, con el número."
    ),
}


def _muestras_del_bosquejo(carpeta: Path, estilos_: list, marca: str = "") -> list[tuple]:
    """Pinta el boceto en cada estilo. Devuelve (estilo, None, ruta_png)."""
    cuerpo = (carpeta / estilos.BOSQUEJO).read_text(encoding="utf-8")
    destino = carpeta / "muestras"
    destino.mkdir(exist_ok=True)
    tanda = []
    for estilo in estilos_:
        html = destino / f"bosquejo-{estilo.id}.html"
        png = destino / f"bosquejo-{estilo.id}.png"
        html.write_text(estilos.envolver_bosquejo(estilo.id, cuerpo, marca), encoding="utf-8")
        # A 390 px: es donde ella lo va a abrir, y un boceto a 720 se leería
        # como una página de escritorio que no va a tener.
        mirar.captura(str(html), png, ancho=390, alto=760)
        tanda.append((estilo, None, png))
    return tanda


def cmd_muestras(con, args) -> int:
    """Las imágenes del catálogo, que son el mecanismo y no un adorno.

    Quien no tiene vocabulario técnico no puede describir un estilo, pero sí
    puede señalar uno (decisión f1). Por eso esto encola una presentación, las
    fotos **numeradas** y una sola pregunta: «¿cuál se parece más?».

    🔴 Numeradas porque sin número contestó «el quinto» queriendo decir el
    sexto, y hubo que preguntarle de nuevo. Un pie «6 · Verde y natural» hace
    que el número que ella lee sea el que el agente apunta.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    grupo = args.grupo

    # 🔴 No se le vuelve a enseñar un catálogo que ya contestó. Salió del primer
    # ensayo con un agente de verdad: escribió `muestras` sin argumentos para
    # mirar cuál había elegido, y le reencoló las seis fotos y la pregunta a
    # alguien que ya había respondido. Un catálogo repetido no se lee como un
    # error del bot: se lee como que no le hicieron caso.
    if grupo == "estilos" and not args.otra_vez:
        ficha = encargos.cargar_ficha(con, encargo_id)
        if ficha.contestada("estilo"):
            return _salir(
                f"ya eligió estilo («{ficha.campos['estilo']}»): volver a "
                "mandarle el catálogo se lee como que no le hiciste caso. "
                "Si de verdad hay que repetirlo, --otra-vez."
            )

    pares = estilos.catalogo().get(grupo)
    if pares is None:
        return _salir(f"«{grupo}» no es un catálogo: son {sorted(estilos.catalogo())}")

    carpeta = encargos.carpeta(encargo_id)
    con_bosquejo = grupo == "estilos" and (carpeta / estilos.BOSQUEJO).is_file()
    if grupo == "estilos" and not con_bosquejo:
        # 🔴 Valla, no consejo (decisión 242). El contrato decía «antes de
        # `encargo muestras`, escribe bosquejo.html» y el primer agente que
        # llegó a esta fase con el contrato nuevo se lo saltó: le mandó a una
        # manicurista seis tiendas de fiados. Un contrato se lee una vez; una
        # orden que se niega se lee cada vez.
        return _salir(
            f"falta `{estilos.BOSQUEJO}` en esta carpeta: escríbelo primero —UNA "
            "pantalla, la que le harías primero, con SUS palabras y SUS datos, "
            "sólo el <main>, contra las clases de estilo-referencia.css y con la "
            "estructura de bosquejo-ejemplo.html— y vuelve a pedir las muestras. "
            "Sin él le mandarías la pantalla de otro negocio."
        )
    if con_bosquejo:
        # 🔴 Su pantalla en seis aires, no la de fiados (decisión 239).
        try:
            ficha = encargos.cargar_ficha(con, encargo_id)
            persona = encargos.ver_persona(con, int(encargos.ver(con, encargo_id)["user_id"]))
            marca = ficha.campos.get("nombre") or encargos.nombre_visible(persona)
            tanda = _muestras_del_bosquejo(
                carpeta, [e for e, _ in pares[args.desde:args.desde + POR_TANDA]], marca)
        except mirar.SinNavegador as exc:
            return _salir(f"no se puede pintar el boceto: {exc}")
    else:
        tanda = [(e, p, estilos.ruta_muestra(e, p))
                 for e, p in pares[args.desde:args.desde + POR_TANDA]]

    # 🔴 Se comprueban TODAS antes de encolar ninguna. Encolando sobre la marcha,
    # una captura que faltara dejaba las otras cinco ya en cola y devolvía error:
    # ella recibía cinco muestras, elegía entre ellas creyendo que las vio todas,
    # y nada en la conversación decía que faltaba una.
    faltan = [ruta.name for _, _, ruta in tanda if not ruta.is_file()]
    if faltan:
        return _salir(
            f"faltan {len(faltan)} capturas por generar ({', '.join(faltan[:3])}…). "
            "Genera el catálogo antes de enseñárselo: "
            "uv run python -c \"from hub import estilos; estilos.generar()\""
        )

    buzon.encolar_salida(con, encargo_id, PRESENTACION["bosquejo" if con_bosquejo else grupo])
    for numero, (estilo, pantalla, ruta) in enumerate(tanda, start=args.desde + 1):
        nombre = estilo.nombre if grupo == "estilos" else pantalla.nombre
        buzon.encolar_salida(
            con, encargo_id, f"{numero} · {nombre}",
            clase="muestras", adjunto=str(ruta),
        )
    buzon.encolar_salida(con, encargo_id, args.pregunta)
    print(f"encoladas {len(tanda)} muestras de «{grupo}» y la pregunta")
    return 0


# Los dos anchos con los que se juzga una pantalla, y el orden importa: el
# primero es donde se va a abrir de verdad.
ANCHOS = ((390, "movil"), (1000, "ancho"))


def cmd_quitar(con, args) -> int:
    """Borra un archivo del sitio, y sólo del sitio (decisión 238).

    El constructor no tiene `rm`: en modo manual pediría permiso y se quedaría
    parado —pasó, con una página que ya había fundido en otra—. Darle `rm`
    entero sería darle `rm` fuera de su carpeta. Esto borra lo que le sobra
    dentro de `sitio/` y nada más: la ruta se resuelve y tiene que quedar
    debajo.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    carpeta = encargos.carpeta(encargo_id).resolve()
    # `app/` también (decisión 244): el implementador tampoco tiene `rm`. Se
    # acepta la ruta relativa a la carpeta («app/x.py») o al sitio («x.html»).
    candidatos = [(carpeta / args.archivo).resolve(), (carpeta / "sitio" / args.archivo).resolve()]
    permitidas = [carpeta / "sitio", carpeta / "app"]
    objetivo = next((c for c in candidatos
                     if any(z in c.parents for z in permitidas) and c not in permitidas), None)
    if objetivo is None:
        return _salir(f"«{args.archivo}» no está dentro de sitio/ ni de app/: sólo se quita lo de ahí")
    if objetivo.name == "estilo.css":
        return _salir("estilo.css no se quita: es el que ella eligió")
    if not objetivo.is_file():
        return _salir(f"no hay ningún archivo «{args.archivo}» ahí")
    objetivo.unlink()
    print(f"quitado {objetivo.relative_to(carpeta)}")
    return 0


def cmd_mirar(con, args) -> int:
    """Pinta lo construido y dice dónde quedaron las capturas.

    🔴 Existe porque el primer constructor real **se fabricó su propio
    navegador**: se instaló Playwright, escribió un script y se salió de su
    carpeta para hacerlo. Hizo lo correcto —su contrato le pide mirar lo que
    construye— con la única herramienta que se le ocurrió, y eso es lo que pasa
    cuando el trabajo que se le pide no está entre las que se le dan.

    🔴 Y el navegador lo elige `mirar.py`, no él: el de Windows **no baja de 500
    px de ancho**, así que una captura «a 390» maqueta a 500 y recorta. Parece
    una pantalla desbordada cuando no lo está — y podría parecer correcta una
    que sí lo está.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    destino = encargos.carpeta(encargo_id) / "vistas"
    if args.url:
        # La app corriendo en local (decisión 244): se mira por HTTP, que es
        # como la verá ella, y sólo en esta máquina.
        if not args.url.startswith(("http://127.0.0.1", "http://localhost")):
            return _salir("sólo se mira una URL local (http://127.0.0.1:…): lo demás no es tuyo")
        try:
            for ancho, nombre in ANCHOS:
                salida = mirar.captura(args.url, destino / f"url-{nombre}.png",
                                       ancho=ancho, alto=args.alto)
                print(f"  {ancho:>4} px  {salida}")
        except mirar.SinNavegador as exc:
            return _salir(str(exc))
        print("\nÁbrelas y míralas de verdad.")
        return 0
    sitio = encargos.carpeta(encargo_id) / "sitio"
    portada = sitio / "index.html"
    if not portada.is_file():
        return _salir(f"todavía no hay «{portada}» que mirar")

    # Todas las pantallas, no sólo la portada (decisión 243): una maqueta
    # navegable con una pantalla rota no se nota mirando la primera.
    paginas = sorted(sitio.glob("*.html"), key=lambda r: (r.name != "index.html", r.name))
    try:
        for pagina in paginas:
            for ancho, nombre in ANCHOS:
                prefijo = "" if pagina.name == "index.html" else f"{pagina.stem}-"
                salida = mirar.captura(str(pagina), destino / f"{prefijo}{nombre}.png",
                                       ancho=ancho, alto=args.alto)
                print(f"  {pagina.name:<22} {ancho:>4} px  {salida}")
    except mirar.SinNavegador as exc:
        return _salir(str(exc))
    print("\nÁbrelas y míralas de verdad: un index.html que existe no es una "
          "pantalla que se entiende.")
    return 0


# ── La app en local, para que el implementador la pruebe (decisión 244) ──────

PID_SERVIDOR = ".servir.pid"
PUERTO_SERVIDOR = ".servir.puerto"


def _servidor_vivo(encargo_id: str) -> int | None:
    """El pid de la app en local si sigue corriendo, o None."""
    import os
    import signal

    archivo = encargos.carpeta(encargo_id) / PID_SERVIDOR
    if not archivo.is_file():
        return None
    try:
        pid = int(archivo.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        archivo.unlink(missing_ok=True)
        return None


def cmd_servir(con, args) -> int:
    """Arranca la app del encargo en local, con una base de prueba vacía.

    Existe por lo mismo que `mirar`: si no se le da la herramienta, el agente
    se la fabrica saliéndose de su carpeta. Corre con el intérprete del hub
    —que ya trae FastAPI y uvicorn, lo mismo que la imagen del servidor— sólo
    en 127.0.0.1, y con `DATOS` apuntando a una carpeta de prueba que cada
    arranque vacía: lo que quede guardado entre pruebas confunde.
    """
    import shutil
    import socket
    import subprocess
    import time
    import urllib.request

    encargo_id = _encargo_actual(con, args.encargo)
    carpeta = encargos.carpeta(encargo_id)
    app_ = carpeta / "app"
    if not (app_ / "main.py").is_file():
        return _salir(f"no hay «{app_ / 'main.py'}» que servir")
    if pid := _servidor_vivo(encargo_id):
        import os
        import signal

        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
    datos = carpeta / "datos-prueba"
    shutil.rmtree(datos, ignore_errors=True)
    datos.mkdir()
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0))
        puerto = s_.getsockname()[1]
    registro = carpeta / "servir.log"
    with registro.open("w") as salida:
        proceso = subprocess.Popen(
            ["uv", "run", "--project", str(config.RAIZ_REPO), "python", "-m", "uvicorn",
             "main:app", "--app-dir", str(app_), "--host", "127.0.0.1", "--port", str(puerto)],
            cwd=str(app_), stdout=salida, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "DATOS": str(datos)},
            start_new_session=True,
        )
    (carpeta / PID_SERVIDOR).write_text(str(proceso.pid))
    (carpeta / PUERTO_SERVIDOR).write_text(str(puerto))
    url = f"http://127.0.0.1:{puerto}"
    tope = time.monotonic() + 25
    while time.monotonic() < tope:
        if proceso.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url + "/salud", timeout=2) as r:
                if r.status == 200:
                    print(f"la app corre en {url} (base de prueba vacía en {datos})\n"
                          f"  curl {url}/api/...   y   ./encargo mirar {url}/\n"
                          "  ./encargo parar cuando termines")
                    return 0
        except Exception:  # noqa: BLE001 - arrancando todavía
            time.sleep(0.5)
    if proceso.poll() is None:
        proceso.terminate()
    (carpeta / PID_SERVIDOR).unlink(missing_ok=True)
    cola = registro.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    return _salir("la app no arrancó o /salud no contesta. Lo último que escribió:\n  "
                  + "\n  ".join(cola))


def cmd_parar(con, args) -> int:
    import os
    import signal

    encargo_id = _encargo_actual(con, args.encargo)
    pid = _servidor_vivo(encargo_id)
    if not pid:
        print("no había ninguna app corriendo")
        return 0
    os.kill(pid, signal.SIGTERM)
    (encargos.carpeta(encargo_id) / PID_SERVIDOR).unlink(missing_ok=True)
    print("app parada")
    return 0


def cmd_deshacer(con, args) -> int:
    """Quita de la cola lo último que encolaste, si todavía no ha salido.

    🔴 Existe por un desliz real, del primer ensayo: una orden escrita sin
    pensar encoló siete mensajes de golpe hacia una persona, y no había forma de
    pararlos. Entre encolar y que el relé mande hay unos segundos, y **lo que
    todavía no ha salido de la máquina sí se puede retirar**; lo que ya salió,
    no — y eso esto no lo finge.

    No borra: marca `descartado`, que sigue viéndose en la conversación. Un
    mensaje que desaparece sin rastro es peor que uno que se ve retirado.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    mios = [m for m in buzon.salientes(con) if m["encargo_id"] == encargo_id]
    if not mios:
        return _salir("no hay nada tuyo en la cola: o ya salió, o no encolaste nada")

    cuantos = min(args.cuantos, len(mios))
    quitados = mios[-cuantos:]
    con.executemany(
        "UPDATE encargo_mensaje SET estado = 'descartado', movido_en = ?, "
        "detalle = 'retirado antes de salir' WHERE id = ?",
        [(encargos.ahora(), m["id"]) for m in quitados],
    )
    encargos.registrar(con, "sale", f"{cuantos} mensaje(s) retirados antes de salir",
                       encargo_id=encargo_id)
    print(f"retirados {cuantos}, que no habían salido:")
    for m in quitados:
        print(f"  — {m['clase']}: {(m['texto'] or m['adjunto'])[:70]}")
    if len(mios) > cuantos:
        print(f"  (quedan {len(mios) - cuantos} en cola)")
    return 0


def cmd_rendirse(con, args) -> int:
    encargo_id = _encargo_actual(con, args.encargo)
    ficha = encargos.cargar_ficha(con, encargo_id)
    if args.fase not in encargos.POR_ID:
        return _salir(f"«{args.fase}» no es una fase: son {list(encargos.POR_ID)}")
    ficha.rendirse(args.fase)
    encargos.guardar_ficha(con, ficha)
    print(texto_de_la_ficha(con, encargo_id))
    return 0


def cmd_nombrar(con, args) -> int:
    """El id es el subdominio, y lo elige ella (decisión 233). Aquí se APUNTA.

    Se acepta lo que dijo tal cual —«Peluches de Ana»— y se comprueba que
    de ahí salga una dirección, que no esté reservada y que no la tenga otro
    encargo. Devuelve cómo quedará para que el agente se lo diga: es la única
    forma de que ella sepa cómo va a quedar antes de que exista.

    🔴 **La carpeta no se mueve aquí** (decisión 241). Se movía, y el agente
    que acababa de teclear la orden se quedaba sentado en una carpeta que ya
    no existía: su `./encargo` desaparecía bajo sus pies, intentaba un `cd` a
    la nueva, y eso caía fuera de su permiso. Y al reabrirlo en la carpeta
    nueva volvía a pedir el nombre, y «está cogido» —por él mismo—. El
    nombre se guarda en la ficha, que cierra la fase, y el encargo se renombra
    **al publicar**, que es cuando ya no hay nadie dentro (234).
    """
    encargo_id = _encargo_actual(con, args.encargo)
    base = encargos.a_id(args.nuevo)
    if not base:
        return _salir(
            f"de «{args.nuevo}» no sale ningún nombre usable como dirección: "
            "pídele otro, con letras o números"
        )
    if base in encargos.RESERVADOS:
        return _salir(f"«{base}» está reservado: lo usa otra cosa en el mismo dominio")
    otro = encargos.ver(con, base)
    if otro and otro["id"] != encargo_id:
        return _salir(f"«{base}» está cogido por otro encargo: hace falta otro nombre")

    ficha = encargos.cargar_ficha(con, encargo_id)
    ficha.responde("nombre", args.nuevo.strip())
    ficha.anota(args.nuevo.strip(), "nombre")
    encargos.guardar_ficha(con, ficha)
    from . import rele_encargos

    destino = rele_encargos.despliegue_configurado()
    donde = f"https://{base}.{destino['dominio']}" if destino else f"«{base}»"
    print(f"Apuntado: «{encargo_id}» se llamará «{base}» y quedará en {donde} — "
          "díselo. La carpeta y el id cambian solos al publicar; tú sigue aquí.")
    return 0


def cmd_proponer(con, args) -> int:
    """Cierra la ficha y manda el plan al dueño. Aquí acaba lo que el agente puede.

    🔴 Lo que sale de aquí es **lo que él va a aprobar**, y aprobarlo autoriza
    gasto y un despliegue público (decisión n14). Por eso el informe es un
    archivo que el agente escribió y se puede releer, no un texto improvisado en
    una llamada: lo aprobado tiene que poder mirarse después tal como era.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    ficha = encargos.cargar_ficha(con, encargo_id)
    abiertas = [f for f in encargos.FASES if not ficha.cerrada(f.id) and f.id != "alcance"]
    if abiertas and not args.igual:
        return _salir(
            "todavía queda alguna fase abierta. Mira `encargo ficha`, y si de "
            "verdad no vas a conseguir más, cierra el hueco con "
            "`encargo rendirse <fase>` — un hueco declarado viaja en el informe; "
            "uno escondido es una sorpresa a mitad de la construcción."
        )
    if not ficha.contestada("alcance") and not args.igual:
        # 🔴 Sin su visto bueno no hay propuesta (decisión 236). Es lo que
        # separa «contestó preguntas y le llegó una página» de «sabe qué le
        # va a llegar y dijo que sí».
        return _salir(
            "falta su visto bueno: dile qué construirías primero y pregúntale si "
            "lo mandamos así o quiere contar más. Cuando diga que va, "
            "`encargo responde alcance \"<lo que dijo>\"`."
        )
    informe = Path(args.informe)
    if not informe.is_file():
        return _salir(f"no existe el informe «{informe}»")

    quien = encargos.dueno(con)
    if not quien:
        return _salir(
            "nadie está marcado como dueño del canal de encargos, así que el "
            "plan no tendría a quién ir. Se marca en el hub, en /encargos."
        )

    huecos = ficha.huecos()
    cabecera = [
        f"Plan del encargo «{encargo_id}» (ronda {ficha.ronda}), listo para tu visto bueno.",
        "",
    ]
    if huecos:
        cabecera += [f"🔴 Sin respuesta: {', '.join(huecos)}.", ""]
    cierre = [
        "",
        "Pulsa «Aprobar» para que empiece, o contesta a ESTE mensaje con qué",
        "cambiarías y lo replanteo. Un «sí» suelto en otro mensaje no dispara nada.",
    ]
    texto = "\n".join(cabecera) + informe.read_text(encoding="utf-8").strip() + "\n".join(cierre)

    fila = encargos.ver(con, encargo_id)
    if encargos.de_confianza(con, int(fila["user_id"])):
        # 🔴 De confianza (decisión 236): el gate de n7 lo pone él POR PERSONA
        # desde el hub, y aquí ya está puesto. El plan le llega igual, como
        # información y no como pregunta —sin `clase="plan"`, así no hay
        # `plan_msg` al que responder—, y el relé lo construye en su vuelta.
        encargos.tocar(con, encargo_id, estado="aprobado")
        encargos.registrar(con, "sale", "plan aprobado por confianza, sin pasar por el dueño",
                           encargo_id=encargo_id)
        buzon.encolar_salida(
            con, encargo_id,
            "Ya tengo lo que necesito. Lo construyo y te aviso en cuanto esté "
            "para que lo veas.")
        buzon.encolar_salida(
            con, encargo_id,
            f"Plan de «{encargo_id}» — es de una persona de confianza, así que se "
            "construye sin esperar tu aprobación. Te lo dejo para que sepas qué va:\n\n"
            + informe.read_text(encoding="utf-8").strip(),
            user_id=int(quien["user_id"]))
        print(f"«{encargo_id}» aprobado por confianza; se construye solo. "
              f"{encargos.nombre_visible(quien)} recibe el plan como aviso.")
        return 0

    encargos.tocar(con, encargo_id, estado="propuesta")
    # 🔴 A ella también se le dice qué pasa ahora (decisión 233). La primera
    # persona real sólo vio que el bot dejó de contestar: entre el plan, la
    # aprobación y la construcción pasaron cuarenta minutos de silencio, y
    # hubiera preferido un «voy a construirlo, te aviso». Lo dice el hub y no
    # el agente porque el agente ya se ha ido.
    buzon.encolar_salida(
        con, encargo_id,
        "Ya tengo lo que necesito. Ahora lo revisa una persona y, si va "
        "adelante, se construye. Te aviso yo en cuanto esté para que lo veas.")
    buzon.encolar_salida(con, encargo_id, texto, clase="plan",
                         user_id=int(quien["user_id"]), botones=buzon.BOTONES_PLAN)
    print(f"el plan sale hacia {encargos.nombre_visible(quien)}. "
          f"El encargo queda en «propuesta» hasta que conteste.")
    return 0


def cmd_listo(con, args) -> int:
    """El constructor dice que está. Avisa a quien lo aprobó, no a quien lo encargó.

    🔴 **El agente no despliega; el relé sí.** Lo que un agente consigue al
    terminar de escribir su último archivo es cambiar un estado. Publicar lo
    hace el relé en su siguiente vuelta, si `encargos.yml` dice dónde —y sin
    pedir otro permiso, porque *«el gate va antes de gastar, no antes de
    publicar»* (decisión n7): el permiso fue el «aprobado». Si no está
    configurado, el aviso trae el comando para hacerlo a mano.
    """
    encargo_id = _encargo_actual(con, args.encargo)
    fila = encargos.ver(con, encargo_id)
    if not fila or fila["estado"] not in ("construyendo", "implementando"):
        return _salir(
            f"«{encargo_id}» está en «{(fila or {}).get('estado', '?')}»: "
            "«listo» sólo cierra algo que se estaba construyendo o implementando"
        )
    if fila["estado"] == "implementando":
        # Lo que se publica es la app (decisión 244): sin main.py no hay qué
        # levantar, y sin static/ la URL no tendría pantallas.
        app_ = encargos.carpeta(encargo_id) / "app"
        if not (app_ / "main.py").is_file() or not (app_ / "static" / "index.html").is_file():
            return _salir(f"faltan «{app_ / 'main.py'}» o «{app_ / 'static/index.html'}»: no habría nada que levantar")
        if _servidor_vivo(encargo_id):
            return _salir("la app sigue corriendo en local: `./encargo parar` primero")
    else:
        portada = encargos.carpeta(encargo_id) / "sitio" / "index.html"
        if not portada.is_file():
            # Un encargo «listo» sin portada da una URL que devuelve un listado de
            # archivos, y quien la abre cree que se rompió el servidor.
            return _salir(f"no hay «{portada}»: no habría nada que abrir")

    quien = encargos.dueno(con)
    if not quien:
        return _salir("nadie está marcado como dueño: el aviso no tendría destino")

    from . import rele_encargos

    encargos.tocar(con, encargo_id, estado="construido")
    if rele_encargos.despliegue_configurado():
        aviso = (f"«{encargo_id}» está {'implementado' if fila['estado'] == 'implementando' else 'construido'}. "
                 "Se publica solo en un momento y os llega la URL a los dos.")
    else:
        aviso = (f"«{encargo_id}» está construido y sin desplegar.\n\n"
                 f"Míralo antes de publicarlo:\n"
                 f"  bash scripts/desplegar-encargo.sh {encargo_id} "
                 f"{encargos.carpeta(encargo_id) / 'sitio'}\n\n"
                 "Eso es un ensayo; añade --va cuando lo hayas visto.")
    buzon.encolar_salida(con, encargo_id, aviso, user_id=int(quien["user_id"]))
    print(f"«{encargo_id}» queda en «construido» y se avisa a "
          f"{encargos.nombre_visible(quien)}.")
    return 0


def cmd_publicado(con, args) -> int:
    """El camino a mano: apunta la URL y la anuncia. El automático es del relé."""
    encargo_id = _encargo_actual(con, args.encargo)
    if not args.url.startswith("https://"):
        return _salir("la URL va completa y con https://")
    encargos.tocar(con, encargo_id, estado="publicado", url=args.url, plan_msg=None)
    buzon.anunciar_publicacion(con, encargo_id, args.url)
    print(f"«{encargo_id}» publicado en {args.url}; el enlace sale hacia los dos.")
    return 0


def cmd_conversacion(con, args) -> int:
    encargo_id = _encargo_actual(con, args.encargo)
    for m in buzon.conversacion(con, encargo_id, args.limite):
        flecha = "→" if m["direccion"] == "sale" else "←"
        print(f"{m['recibido_en'][11:16]} {flecha} [{m['estado']}] {m['texto'][:200]}")
    return 0


ORDENES = {
    "ficha": cmd_ficha,
    "preguntar": cmd_preguntar,
    "responde": cmd_responde,
    "anota": cmd_anota,
    "decir": cmd_decir,
    "muestras": cmd_muestras,
    "mirar": cmd_mirar,
    "quitar": cmd_quitar,
    "deshacer": cmd_deshacer,
    "rendirse": cmd_rendirse,
    "nombrar": cmd_nombrar,
    "servir": cmd_servir,
    "parar": cmd_parar,
    "proponer": cmd_proponer,
    "listo": cmd_listo,
    "publicado": cmd_publicado,
    "conversacion": cmd_conversacion,
}


def construir_parser() -> argparse.ArgumentParser:
    partes = argparse.ArgumentParser(
        prog="encargo", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    partes.add_argument("--encargo", default="",
                        help="contra cuál trabajar; se deduce si sólo hay uno")
    sub = partes.add_subparsers(dest="orden", required=True)

    sub.add_parser("ficha", help="qué sé, qué falta y qué toca preguntar")

    p = sub.add_parser("preguntar", help="hace la siguiente pregunta que toque")
    p.add_argument("texto", nargs="?", default="",
                   help="con tus palabras; sin esto, la de la fase")

    p = sub.add_parser("responde", help="aterriza una respuesta en su casilla")
    p.add_argument("fase")
    p.add_argument("texto")

    p = sub.add_parser("anota", help="guarda lo que contó, toque o no toque")
    p.add_argument("texto")
    p.add_argument("--fase", default="")

    p = sub.add_parser("decir", help="le dice algo")
    p.add_argument("texto")

    p = sub.add_parser("muestras", help="le manda el catálogo para que elija")
    p.add_argument("grupo", nargs="?", default="estilos",
                   choices=["estilos", "pantallas"])
    p.add_argument("--desde", type=int, default=0, help="para mandar la segunda tanda")
    p.add_argument("--pregunta",
                   default="¿Cuál se parece más a lo que te gustaría? "
                           "Dime el nombre o el número, lo que te sea más fácil.")
    p.add_argument("--otra-vez", action="store_true", dest="otra_vez",
                   help="aunque ya haya elegido (tendrás que justificarlo)")

    p = sub.add_parser("quitar", help="borra un archivo del sitio (sólo del sitio)")
    p.add_argument("archivo")

    p = sub.add_parser("mirar", help="pinta lo construido para poder juzgarlo")
    p.add_argument("url", nargs="?", default="")
    p.add_argument("--alto", type=int, default=1200)

    sub.add_parser("servir", help="arranca la app en local con una base de prueba")
    sub.add_parser("parar", help="apaga la app que arrancó servir")

    p = sub.add_parser("deshacer", help="retira de la cola lo que aún no ha salido")
    p.add_argument("cuantos", nargs="?", type=int, default=1)

    p = sub.add_parser("rendirse", help="declara el hueco y sigue")
    p.add_argument("fase")

    p = sub.add_parser("nombrar", help="el nombre que ella quiere; se convierte en dirección")
    p.add_argument("nuevo")

    p = sub.add_parser("proponer", help="cierra la ficha y manda el plan al dueño")
    p.add_argument("informe")
    p.add_argument("--igual", action="store_true",
                   help="aunque queden fases abiertas (tendrás que justificarlo)")

    sub.add_parser("listo", help="lo construido está; avisa a quien lo aprobó")

    p = sub.add_parser("publicado", help="apunta la URL y se la manda a los dos")
    p.add_argument("url")

    p = sub.add_parser("conversacion", help="lo hablado, en orden")
    p.add_argument("--limite", type=int, default=40)
    return partes


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    try:
        codigo = ORDENES[args.orden](con, args)
        con.commit()
        return codigo
    finally:
        con.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
