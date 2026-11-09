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
                                              "compromiso", "bitacora", "llamada", "persona")},
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
    no es lanzar."""
    assert SRC.is_dir()
    permitidos = {"procesos.py"}
    fuera = [str(a.relative_to(SRC)) for a in SRC.rglob("*.py")
             if str(a.relative_to(SRC)) not in permitidos
             and re.search(r"start_new_session|\[\s*[\"']systemd-run[\"']", a.read_text(encoding="utf-8"))]
    assert not fuera, f"lanzan por su cuenta en vez de por procesos.desasir: {fuera}"


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
    ("repos._hay_git", "api.py"),                                 # sin ficha: apuntado en C-0088
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
