"""Cada tabla la escribe su módulo dueño, y nadie más (C-0050, decisión 338).

`web.py` llegó a escribir con SQL copiado las solicitudes y los turnos del
secretario y las personas de encargos: dos sitios que escriben lo mismo
divergen en cuanto cambia el esquema. La puerta de cada una está en el
catálogo de capacidades de `MAPA.md`; esto vigila que no se abra otro camino.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "hub"

#: tabla → archivos que pueden escribirla (relativos a src/hub).
DUENOS = {
    "solicitud": {"secretario/memoria.py", "secretario/herramientas.py"},  # crearla es del catálogo de acciones
    "turno": {"secretario/memoria.py", "secretario/conversacion.py"},
    "encargo_persona": {"encargos.py", "db.py"},
    # La cola, el encargo y su rastro (C-0137): el relé y la CLI entran por sus puertas.
    "encargo_mensaje": {"buzon.py"},
    "encargo": {"encargos.py"},
    "encargo_registro": {"encargos.py"},
    # La memoria del secretario (C-0064): su módulo, y la conversación su hilo.
    **{t: {"secretario/memoria.py"} for t in ("evento", "suscripcion", "fuente_estado", "estado", "nota",
                                              "compromiso", "bitacora", "llamada", "persona",
                                              # qué notas se le sirven al modelo: `apuntar_lectura` (C-0424)
                                              "nota_uso")},
    "hilo": {"secretario/conversacion.py"},
    "idea": {"ideas.py"},  # el tablero: web, secretario y CLI entran por ideas.apuntar (342)
    "asunto": {"secretario/asuntos.py"},  # lo que espera del dueño: sólo sus marcas y lo propio (380)
}


@pytest.mark.parametrize("tabla", sorted(DUENOS))
def test_solo_su_modulo_escribe_la_tabla(tabla):
    assert SRC.is_dir(), "sin el código delante este test pasaría sin mirar"
    # Sobre el archivo entero y no línea a línea: un SQL partido entre el verbo
    # y la tabla (`"UPDATE "` + `"evento SET…"`) se escapaba (revisor de C-0064).
    escritura = re.compile(
        rf"\b(INSERT\s+(OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)[\s\"']+{tabla}\b", re.I)
    intrusos = []
    for archivo in SRC.rglob("*.py"):
        rel = str(archivo.relative_to(SRC))
        if rel in DUENOS[tabla]:
            continue
        texto = archivo.read_text(encoding="utf-8")
        for m in escritura.finditer(texto):
            intrusos.append(f"{rel}:{texto.count(chr(10), 0, m.start()) + 1}")
    assert not intrusos, f"`{tabla}` se escribe fuera de su puerta: {intrusos}"


#: tabla → archivos que pueden leerla. En encargos también se leía por
#: fuera —el relé buscaba en el registro, el entrevistador en el encargo, el
#: chat web en las personas— y una lectura copiada se queda atrás igual que
#: una escritura en cuanto cambia lo que significa una columna (C-0137).
LECTORES = {
    "encargo_mensaje": {"buzon.py"},
    "encargo": {"encargos.py"},
    "encargo_persona": {"encargos.py"},
    "encargo_registro": {"encargos.py"},
}


@pytest.mark.parametrize("tabla", sorted(LECTORES))
def test_solo_su_modulo_lee_la_tabla(tabla):
    assert SRC.is_dir()
    lectura = re.compile(rf"\b(FROM|JOIN)[\s\"']+{tabla}\b", re.I)
    intrusos = []
    for archivo in SRC.rglob("*.py"):
        rel = str(archivo.relative_to(SRC))
        if rel in LECTORES[tabla]:
            continue
        texto = archivo.read_text(encoding="utf-8")
        for m in lectura.finditer(texto):
            intrusos.append(f"{rel}:{texto.count(chr(10), 0, m.start()) + 1}")
    assert not intrusos, f"`{tabla}` se lee fuera de su puerta: {intrusos}"


@pytest.mark.parametrize("modulo", ["salud.py", "guia.py"])
def test_salud_y_guia_no_consultan_la_base_por_su_cuenta(modulo):
    """Contaban slots, proyectos y repos con su propio SQL (C-0056): lo que
    enseñan sale de `api.py`, que les pasa los datos ya leídos, igual que ya
    les pasaba los paneles y si una carpeta existe."""
    texto = (SRC / modulo).read_text(encoding="utf-8")
    assert not re.search(r"\.execute\(|\bSELECT\b", texto), f"{modulo} consulta la base por su cuenta"


def test_solo_la_puerta_escribe_en_la_cola_de_timbres():
    """El secretario escribía el JSON del timbre a mano, con un formato propio
    que sólo el relé conocía (C-0046). La cola es `timbre.tocar` (341)."""
    assert SRC.is_dir()
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if a.name != "timbre.py" and re.search(r"""["']timbres["']""", a.read_text(encoding="utf-8"))]
    assert not fuera, f"escriben o arman la carpeta de timbres por su cuenta: {fuera}"


def test_solo_la_puerta_lanza_procesos_que_sobreviven_al_servicio():
    """`start_new_session` no saca del cgroup, y cada camino propio era un
    proceso que moría al reiniciar el servicio (C-0148). La puerta es
    `procesos.desasir` (344). `encargos_cli servir` ya pasa por `encierro`,
    que lanza por ella (C-0145). Preguntar si existe (`which("systemd-run")`)
    no es lanzar. Un grupo de procesos propio (`process_group`) tampoco saca
    del cgroup y también se vigila: sólo `secretario/motor.py`, que lo usa
    para matar a `claude` con su servidor MCP al cortar una llamada (C-0241),
    no para que sobreviva, y `comandos.py`, para matar con su `git` la orden
    de una lista que se pasa del tope (C-0507)."""
    assert SRC.is_dir()
    vigilado = r"start_new_session|process_group|\[\s*[\"']systemd-run[\"']"
    # Lo que cada uno puede usar de eso: la puerta, todo; el motor y los comandos, su grupo.
    permitido = {"procesos.py": vigilado, "secretario/motor.py": r"process_group=0",
                 "comandos.py": r"process_group=0"}
    fuera = []
    for a in SRC.rglob("*.py"):
        nombre = str(a.relative_to(SRC))
        texto = re.sub(permitido.get(nombre, r"(?!)"), "", a.read_text(encoding="utf-8"))
        if re.search(vigilado, texto):
            fuera.append(nombre)
    assert not fuera, f"lanzan por su cuenta en vez de por procesos.desasir: {fuera}"


def test_solo_salud_y_el_panico_accionan_servicios():
    """Encender es `salud.encender`, con su lista cerrada (400); reiniciar, el
    botón de pánico desde `hub-canal` (151). Un `systemctl enable/start/stop`
    suelto en otro módulo, o la orden de `salud` llamada desde fuera, es un
    servicio accionado sin esa lista. Preguntar (`is-active`, `is-enabled`) no
    es accionar. `actualizar.sh` también reinicia servicios, pero es un guion
    entero que lanza `actualizacion` (296), no una orden suelta."""
    accion = re.compile(r"""["']systemctl["'][^\n]*["'](?:enable|disable|start|stop|restart)["']""")
    # La de `salud`, no cualquier `_orden` (búsqueda y WhatsApp tienen la suya).
    orden_de_salud = re.compile(r"salud\s*\.\s*_orden\b|from\s+\S*salud\s+import[^\n]*\b_orden\b")
    fuera = []
    for a in SRC.rglob("*.py"):
        nombre, texto = str(a.relative_to(SRC)), a.read_text(encoding="utf-8")
        if (nombre != "panico.py" and accion.search(texto)) or (nombre != "salud.py" and orden_de_salud.search(texto)):
            fuera.append(nombre)
    assert not fuera, f"accionan servicios por su cuenta: {fuera}"
    # Que el vigía siga viendo las formas permitidas: si no, no vigila nada.
    assert accion.search((SRC / "panico.py").read_text(encoding="utf-8")), "el vigía ya no ve la forma de panico.py"
    assert orden_de_salud.search("from .salud import _orden") and orden_de_salud.search("salud._orden('stop', x)")


#: función → el único archivo que la define. Dos copias de lo mismo divergen
#: en cuanto se arregla una de ellas (auditoría del 3-nov).
UNA_DEFINICION = {
    # Dónde abrir una ventana de un proyecto: la misma para slots y agentes (C-0090).
    "sesion_para": "slots.py",
    # La huella de un archivo de kit y si un binario está: kits, catálogo y CLI (C-0124).
    "huella_de_archivo": "kits.py",
    "hay_binario": "kits.py",
    # La hora en UTC para la base: había nueve copias (C-0051).
    "ahora": "reloj.py",
    # La hora local: el secretario y la web tenían cada uno la suya (C-0051).
    "zona": "reloj.py",
    "a_local": "reloj.py",
    # Leer una fecha guardada para comparar: iba ya por la sexta copia (C-0186).
    "instante": "reloj.py",
}


@pytest.mark.parametrize("copia", ["catalogo.py:_hash", "kits_cli.py:_hay", "lienzos.py:_ahora", "acceso.py:_ahora",
                                   "buzon.py:_momento", "rele_encargos.py:_momento"])
def test_no_quedan_las_copias_de_las_funciones_compartidas(copia):
    archivo, funcion = copia.split(":")
    assert not re.search(rf"^def {funcion}\(", (SRC / archivo).read_text(encoding="utf-8"), re.M), copia


@pytest.mark.parametrize("funcion", sorted(UNA_DEFINICION))
def test_cada_funcion_compartida_se_define_en_un_solo_sitio(funcion):
    assert SRC.is_dir()
    patron = re.compile(rf"^\s*def {funcion}\(", re.M)
    donde = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                   if patron.search(a.read_text(encoding="utf-8")))
    assert donde == [UNA_DEFINICION[funcion]], f"`{funcion}` se define en {donde}"


def test_la_capa_base_se_define_en_un_solo_sitio():
    """Su versión y dónde vive (`.claude/hub/`) estaban en `base` y en `kits`
    (C-0117): subir la versión en uno dejaba al otro midiendo la vieja."""
    assert SRC.is_dir()
    for patron in (r"^VERSION_BASE\s*=", r"""["']\.claude["']\s*/\s*["']hub["']"""):
        donde = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                       if re.search(patron, a.read_text(encoding="utf-8"), re.M))
        assert donde == ["kits.py"], f"`{patron}` en {donde}"


def test_el_id_de_una_conversacion_se_comprueba_en_un_solo_sitio():
    """Había tres expresiones para lo mismo, una más laxa que las otras
    (C-0092). La pregunta es `modelos.es_sesion`."""
    assert SRC.is_dir()
    uuid = re.compile(r"\[0-9a-f(A-F)?\]\{8\}|\[0-9a-fA-F-\]\{8,")
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if a.name != "modelos.py" and uuid.search(a.read_text(encoding="utf-8"))]
    assert not fuera, f"comprueban un id de conversación por su cuenta: {fuera}"


@pytest.mark.parametrize("patron", [
    r"""["']\.claude["']\s*/\s*["']projects["']""",   # la raíz, armada a trozos
    r"""\.claude/projects["']""",                      # o en una sola cadena
    r"""HUB_TRANSCRIPTS["']""",                        # la variable, leída por su cuenta
    r"\bTRANSCRIPTS\b",                                # la constante de antes
    r"\bslug_de\(",                                    # la carpeta de un cwd, armada a mano
])
def test_la_carpeta_de_los_transcripts_se_arma_en_un_solo_sitio(patron):
    """La raíz se definía en tres sitios y sólo uno leía `HUB_TRANSCRIPTS`
    (C-0049), y la carpeta de un cwd se armaba a mano en cuatro (C-0091). Las
    puertas son `transcripts.raiz` y `transcripts.directorio_de`."""
    assert SRC.is_dir()
    fuera = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                   if a.relative_to(SRC) != Path("transcripts.py")
                   and re.search(patron, a.read_text(encoding="utf-8")))
    assert not fuera, f"`{patron}` fuera de transcripts.py: {fuera}"


def test_nadie_le_habla_a_tmux_saltandose_el_adaptador():
    """`terminal.py` llamaba siete veces a `tmux._correr` con órdenes armadas a
    mano (C-0087): eso se salta la validación del destino (regla dura 9) y
    deja la orden fuera de donde se buscan. Cada orden es una función de
    `tmux.py`."""
    assert SRC.is_dir()
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if a.name != "tmux.py" and "tmux._correr" in a.read_text(encoding="utf-8")]
    assert not fuera, f"llaman a tmux._correr por su cuenta: {fuera}"


@pytest.mark.parametrize("puerta", [
    "orquestador.guardrail_de", "orquestador.exigir", "orquestador.editar", "orquestador.cargar",
    "slots.crear", "tmux.validar_sesion", "tmux.validar_panel", "tmux.matar_panel",
    "entrevistador.dar_de_alta", "agentes.confiar", "conversaciones.ficha",
])
def test_las_puertas_del_catalogo_dicen_su_porque(puerta):
    """Quien llega por `MAPA.md` a una puerta tiene que leer en ella por qué es
    así sin ir al código de dentro (C-0095)."""
    import importlib
    import inspect
    modulo, nombre = puerta.split(".")
    assert inspect.getdoc(getattr(importlib.import_module(f"hub.{modulo}"), nombre)), puerta


def test_solo_el_encierro_crea_namespaces():
    """Lo que escribe un agente corre encerrado por una sola puerta (350):
    otro `unshare` suelto sería un encierro sin la lista blanca ni el
    `pivot_root`, que es lo que lo hace un encierro."""
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if a.name != "encierro.py" and re.search(r"[\"']unshare[\"']", a.read_text(encoding="utf-8"))]
    assert not fuera, f"crean namespaces por su cuenta: {fuera}"


def test_solo_tres_modulos_lanzan_powershell():
    """Una orden libre en su Windows va por `orden_pc`, con el analizador y el
    sí del dueño (C-0240, 404); los guiones fijos, por `diagnostico`; `maquina`
    sólo lo encuentra. Otro módulo que lo lanzara sería una terminal sin nada
    de eso."""
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if a.name not in ("diagnostico.py", "maquina.py", "orden_pc.py")
             and re.search(r"powershell(\.exe)?[\"']", a.read_text(encoding="utf-8"), re.I)]
    assert not fuera, f"lanzan PowerShell por su cuenta: {fuera}"


def _codigo(archivo: str) -> str:
    return re.sub(r'""".*?"""|#[^\n]*', "", (SRC / archivo).read_text(encoding="utf-8"), flags=re.S)


@pytest.mark.parametrize("modulo, puerto, caminos", [
    ("puente.py", r"\b8794\b|PUENTE_PUERTO", ['"/api/estado"']),
    ("estudio.py", r"\b8795\b|ESTUDIO_PUERTO", ['"/api/salud"', '"/api/proyectos"']),
])
def test_el_puerto_de_un_programa_aparte_solo_aparece_en_su_modulo_y_ahi_no_hay_post(modulo, puerto, caminos):
    """Al Puente KVM (438) y al estudio (461) sólo se les hace un GET a
    loopback, desde su módulo y por `consulta_local`: dar el control, aprobar
    y contestar son de la persona en su pantalla. Su puerto escrito en otro
    sitio sería un segundo camino hacia él, y un POST, un socket propio o su
    archivo de entorno en su módulo, justo lo que no debe hacer."""
    textos = [a for a in SRC.rglob("*") if a.is_file() and a.suffix in (".py", ".html", ".js")]
    con_puerto = sorted(str(a.relative_to(SRC)) for a in textos
                        if re.search(puerto, a.read_text(encoding="utf-8")))
    assert con_puerto == [modulo], con_puerto
    codigo = _codigo(modulo)
    assert re.findall(r'consulta_local\.pedir_json\(puerto\(\), ("/[^"]*")', codigo) == caminos, \
        "el vigía ya no ve sus preguntas"
    for prohibido in (r"\bPOST\b", r"\bPUT\b", r"\bDELETE\b", r"\bPATCH\b", r"urlopen", r"http\.client",
                      r"\bsocket\b", r"\.send", r"body\s*=", r"\.config", r"entorno", r"open\("):
        assert not re.search(prohibido, codigo), f"{modulo}: {prohibido}"


def test_el_cliente_de_los_programas_aparte_solo_sabe_hacer_un_get_a_loopback():
    """`consulta_local` es el único cliente HTTP hacia los programas aparte
    (461): una petición, escrita entera, GET y a `127.0.0.1`. Un segundo
    cliente sería el camino duplicado que el catálogo existe para evitar."""
    codigo = _codigo("consulta_local.py")
    assert re.findall(r'"GET \{camino\} HTTP/1\.0', codigo) == ['"GET {camino} HTTP/1.0'], \
        "el vigía ya no ve la petición"
    assert len(re.findall(r"\.send(all)?\(", codigo)) == 1, "consulta_local.py manda algo más que su GET"
    assert re.search(r'ANFITRION = "127\.0\.0\.1"', codigo)
    for prohibido in (r"\bPOST\b", r"\bPUT\b", r"\bDELETE\b", r"\bPATCH\b", r"urlopen", r"http\.client",
                      r"body\s*=", r"open\("):
        assert not re.search(prohibido, codigo), f"consulta_local.py: {prohibido}"
    fuera = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                   if a.name not in ("consulta_local.py", "puente.py", "estudio.py")
                   and re.search(r"\bconsulta_local\b", re.sub(r'""".*?"""|#[^\n]*', "",
                                                                a.read_text(encoding="utf-8"), flags=re.S)))
    assert not fuera, f"usan el cliente de los programas aparte por su cuenta: {fuera}"


def test_solo_la_costura_de_lectura_le_pregunta_al_puente():
    """`puente.estado` se llama al pintar /puente, por `api.puente`, y en
    ningún otro sitio: ni el raíl ni el muestreo le preguntan (438)."""
    vigia = re.compile(r"from\s+\.+\s+import[^\n]*\bpuente\b|import\s+hub\.puente|\bpuente\.estado\(")
    fuera = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                   if a.name not in ("api.py", "puente.py")
                   and vigia.search(re.sub(r'""".*?"""|#[^\n]*', "", a.read_text(encoding="utf-8"), flags=re.S)))
    assert not fuera, f"le preguntan al puente por su cuenta: {fuera}"
    assert vigia.search((SRC / "api.py").read_text(encoding="utf-8")), "el vigía ya no ve a api.puente"


def test_solo_la_costura_de_lectura_le_pregunta_al_estudio():
    """`estudio.estado` se llama al pintar /estudio, por `api.estudio`, y en
    ningún otro sitio: ni el raíl ni el muestreo le preguntan (461).

    `componentes.py` importa el módulo para sus pasos y su encargo —el kit, el
    catálogo y el puerto, que no le preguntan nada (C-0503, 463)—, y lo que
    mide se lo da `api.estudio`: puede importarlo, pero no llamar a `estado`."""
    vigia = re.compile(r"from\s+\.+\s+import[^\n]*\bestudio\b|import\s+hub\.estudio|\bestudio\.estado\(")
    pregunta = re.compile(r"\bestudio\.estado\b|from\s+\.+estudio\s+import[^\n]*\bestado\b")
    sin_comentarios = lambda a: re.sub(r'""".*?"""|#[^\n]*', "", a.read_text(encoding="utf-8"),  # noqa: E731
                                       flags=re.S)
    fuera = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
                   if a.name not in ("api.py", "estudio.py")
                   and (pregunta if a.name == "componentes.py" else vigia).search(sin_comentarios(a)))
    assert not fuera, f"le preguntan al estudio por su cuenta: {fuera}"
    assert vigia.search((SRC / "api.py").read_text(encoding="utf-8")), "el vigía ya no ve a api.estudio"


def test_las_pantallas_solo_se_recorren_por_navegacion_visibles():
    """`navegacion.SECCIONES` lleva también las pantallas de las herramientas
    opcionales: recorrerlas a pelo para enseñarlas o buscarlas las deja
    asomar apagadas, como le pasó a «dónde está» del secretario (438). Fuera
    de `navegacion.py`, nadie nombra `SECCIONES` en el código: se pide
    `navegacion.visibles(encendidas)` (o `con_cifras`, que va por ella)."""
    vigia = re.compile(r"\bSECCIONES\b")
    sin_comentarios = re.compile(r'""".*?"""|#[^\n]*|\{#.*?#\}', re.S)
    fuera = sorted(str(a.relative_to(SRC)) for a in SRC.rglob("*")
                   if a.is_file() and a.suffix in (".py", ".html", ".js") and a.name != "navegacion.py"
                   and vigia.search(sin_comentarios.sub("", a.read_text(encoding="utf-8"))))
    assert not fuera, f"recorren las secciones a pelo: {fuera}"
    # Y dentro de `navegacion.py`, lo que enseña pasa por `visibles`.
    propio = sin_comentarios.sub("", (SRC / "navegacion.py").read_text(encoding="utf-8"))
    cuerpo = propio.split("def con_cifras", 1)[1]
    assert "visibles(" in cuerpo and "SECCIONES" not in cuerpo, "con_cifras ya no pasa por visibles"


# ── Un privado de otro módulo no es una puerta (C-0088) ─────────────────────
#
# `agentes._confiar` lo llamaban seis módulos: era una puerta sin serlo, sin
# fila en MAPA y con un guion bajo que decía «esto no lo uses». Cuando algo de
# otro módulo hace falta fuera, se hace público y se nombra; si no debería
# hacer falta, se arregla quien lo llama.

#: Los que quedan, con la ficha que lo resuelve (o dónde se apuntó si aún no
#: la tiene). Esta lista SÓLO ENCOGE: un uso nuevo pone el test en rojo, y
#: uno arreglado también, hasta que se borra de aquí.
PRIVADOS_AJENOS_PENDIENTES = {
    ("asistente._cuadro", "tui.py"),                              # C-0080: va a `tui`
    ("constructor._slot_llamado", "entrevistador.py"),            # C-0136
    ("constructor._slot_llamado", "implementador.py"),            # C-0136
    ("orquestador._sesiones_de_claude", "snapshotter.py"),        # C-0082
    ("secretario.conversacion._dueno", "secretario/servicio.py"),  # C-0071
}


def _modulo_de(archivo: Path) -> str:
    partes = list(archivo.relative_to(SRC.parent).with_suffix("").parts)
    return ".".join(partes[:-1] if partes[-1] == "__init__" else partes)


def _privados_ajenos(archivo: Path, modulos: set[str]) -> set[tuple[str, str]]:
    import ast

    actual = _modulo_de(archivo)
    paquete = actual if archivo.name == "__init__.py" else actual.rpartition(".")[0]
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    nombres: dict[str, str] = {}   # nombre local → módulo de hub al que apunta
    usos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            base = nodo.module or ""
            if nodo.level:
                raiz = paquete.split(".")[: len(paquete.split(".")) - (nodo.level - 1)]
                base = ".".join(raiz + ([nodo.module] if nodo.module else []))
            for a in nodo.names:
                if f"{base}.{a.name}" in modulos:
                    nombres[a.asname or a.name] = f"{base}.{a.name}"
                elif base in modulos and base != actual and a.name.startswith("_") \
                        and not a.name.startswith("__"):
                    usos.add((f"{base}.{a.name}", str(archivo.relative_to(SRC))))
        elif isinstance(nodo, ast.Import):
            for a in nodo.names:
                if a.name in modulos:
                    nombres[a.asname or a.name] = a.name
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name)
                and nodo.value.id in nombres and nombres[nodo.value.id] != actual
                and nodo.attr.startswith("_") and not nodo.attr.startswith("__")):
            usos.add((f"{nombres[nodo.value.id]}.{nodo.attr}", str(archivo.relative_to(SRC))))
    return {(m.removeprefix("hub."), donde) for m, donde in usos}


def test_nadie_usa_lo_privado_de_otro_modulo_salvo_lo_pendiente():
    # Sin el código delante no habría usos, y con la lista vacía pasaría.
    assert SRC.is_dir() and (SRC / "api.py").is_file()
    modulos = {_modulo_de(a) for a in SRC.rglob("*.py")}
    usados = set().union(*(_privados_ajenos(a, modulos) for a in SRC.rglob("*.py")))
    nuevos = sorted(usados - PRIVADOS_AJENOS_PENDIENTES)
    assert not nuevos, ("privados de otro módulo usados como puerta: hazlos públicos "
                        "(y si son una puerta del catálogo, con su fila en MAPA), o no "
                        f"los llames: {nuevos}")
    arreglados = sorted(PRIVADOS_AJENOS_PENDIENTES - usados)
    assert not arreglados, f"ya no se usan: bórralos de PRIVADOS_AJENOS_PENDIENTES: {arreglados}"


def test_el_vigia_de_privados_ve_cada_forma_de_importar(tmp_path, monkeypatch):
    """Que no pase en verde por no mirar: por atributo, con alias, desde un
    subpaquete (`from .. import`) y con `from … import _x`. Y lo propio de
    cada módulo no cuenta."""
    paquete = tmp_path / "hub"
    (paquete / "sub").mkdir(parents=True)
    (paquete / "a.py").write_text("def _x(): pass\n_x()\n", encoding="utf-8")
    (paquete / "b.py").write_text("from . import a\na._x()\n", encoding="utf-8")
    (paquete / "c.py").write_text("from .a import _x\n", encoding="utf-8")
    (paquete / "d.py").write_text("from . import a as _a\n_a._x()\n", encoding="utf-8")
    (paquete / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (paquete / "sub" / "e.py").write_text("from .. import a\na._x()\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "SRC", paquete)
    modulos = {_modulo_de(a) for a in paquete.rglob("*.py")}
    assert _privados_ajenos(paquete / "a.py", modulos) == set()
    for nombre in ("b.py", "c.py", "d.py", "sub/e.py"):
        assert _privados_ajenos(paquete / nombre, modulos) == {("a._x", nombre)}, nombre


# ── Lo que pinta la UI sale de `api.py` (C-0382, C-0101) ─────────────────────
#
# «Una sola costura de lectura»: el MCP se monta sobre `api.py`, y una ruta GET
# que lee por su cuenta es una lectura que el MCP no ve. Se mira el cuerpo de
# cada ruta GET de `web.py` (con `ast`, no con texto: un comentario que nombre
# `lienzos.leer` no es una llamada).

#: Módulos que una ruta GET no llama directamente: su lectura tiene función en `api`.
LECTURAS_DE_API = {
    "lienzos": "api.lienzos / api.lienzo",
    "transcripts": "api.sesiones / api.sesion",
    "registry.cargar": "api (el registro lo lee la costura)",
}

#: Rutas que no se miran, con su porqué.
FUERA_DE_LA_COSTURA = {
    # El asistente se retira (C-0101 lo deja fuera a propósito): sus rutas no
    # se tocan aquí.
    "/api/asistente", "/api/asistente/conversaciones",
}


def _rutas_get_que_leen_por_fuera(vigilados: dict[str, str]) -> list[str]:
    import ast

    arbol = ast.parse((SRC / "web.py").read_text(encoding="utf-8"))
    intrusos = []
    for nodo in arbol.body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        rutas = [d.args[0].value for d in nodo.decorator_list
                 if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                 and d.func.attr == "get" and d.args]
        if not rutas or rutas[0] in FUERA_DE_LA_COSTURA:
            continue
        for n in ast.walk(nodo):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)):
                continue
            modulo, funcion = n.func.value.id, n.func.attr
            if modulo in vigilados or f"{modulo}.{funcion}" in vigilados:
                intrusos.append(f"{rutas[0]} → {modulo}.{funcion} (va por {vigilados.get(modulo) or vigilados[f'{modulo}.{funcion}']})")
    return intrusos


def test_ninguna_ruta_get_lee_lienzos_sesiones_ni_el_registro_por_su_cuenta():
    intrusos = _rutas_get_que_leen_por_fuera(LECTURAS_DE_API)
    assert not intrusos, "lecturas que se saltan api.py:\n" + "\n".join(intrusos)


#: Lo que C-0101 apuntó el 3-nov, sin las rutas del asistente.
LECTURAS_DE_API_C0101 = {
    "busqueda": "api.buscar",
    "canal.ver_pregunta": "api.pregunta",
    "canal.preguntas": "api.preguntas",
    "comandos": "api.comandos_preparados",
    "terminal": "api.sesiones_tmux",
    "tmux": "api (`ventana_activa`, `ventanas_de_sesion`…)",
}


def test_ninguna_ruta_get_busca_pregunta_ni_mira_tmux_por_su_cuenta():
    """C-0101: la paleta de búsqueda, las preguntas del canal, los comandos
    preparados de /archivos y las sesiones de /trabajo, por `api`, para que el
    MCP vea lo mismo que la CLI. Y lo que una ruta GET llama de `web.py` sin
    módulo delante (un `_ayudante`) también cuenta: ahí se escondía el `tmux`
    de /trabajo."""
    import ast

    arbol = ast.parse((SRC / "web.py").read_text(encoding="utf-8"))
    ayudantes = {n.name: n for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    intrusos = list(_rutas_get_que_leen_por_fuera(LECTURAS_DE_API_C0101))
    for nodo in ayudantes.values():
        rutas = [d.args[0].value for d in nodo.decorator_list
                 if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                 and d.func.attr == "get" and d.args]
        if not rutas or rutas[0] in FUERA_DE_LA_COSTURA:
            continue
        for n in ast.walk(nodo):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ayudantes:
                for m in ast.walk(ayudantes[n.func.id]):
                    if (isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute)
                            and isinstance(m.func.value, ast.Name) and m.func.value.id == "tmux"):
                        intrusos.append(f"{rutas[0]} → {n.func.id} → tmux.{m.func.attr}")
    assert not intrusos, "lecturas que se saltan api.py:\n" + "\n".join(intrusos)
