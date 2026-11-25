"""El nombre visible de una ventana lo pone el dueño o nadie (C-0479, decisión 454).

Sale de lo que se vio en el teléfono el 24-nov: en el slot de prototipos el
árbol del escritorio decía «Servidor de pruebas con Forge» y la franja de
pestañas —lo único que nombra las ventanas en el teléfono— decía
«prototipos», el nombre del slot. Dos fuentes para la misma ventana:
el árbol tomaba el título del panel y la franja daba por renombrada a mano toda
ventana con `automatic-rename` apagado, y cualquier `-n` lo apaga.

Lo de tmux se prueba con tmux de verdad, en un servidor propio: que `##` quede
literal y que `#(` no ejecute nada no se puede ver con un doble.
"""

from __future__ import annotations

import os
import shutil
import time

import pytest

import arnes_tmux
from hub import api, slots, snapshotter, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor

con_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="sin tmux")


# ── la puerta, sin tmux ──────────────────────────────────────────────────────

def test_una_ventana_automatica_se_llama_como_su_titulo():
    assert tmux.etiqueta_de_ventana(
        "claude", False, "✳ Servidor de pruebas con Forge", "/tmp", "claude",
    ) == "Servidor de pruebas con Forge"


def test_una_ventana_renombrada_por_el_dueno_se_llama_como_la_llamo():
    assert tmux.etiqueta_de_ventana(
        "lambda SQS", True, "✳ Debugar lambda", "/tmp", "claude", {"work", "back"},
    ) == "lambda SQS"


@pytest.mark.parametrize("heredado", ["prototipos", "planos"])
def test_una_ventana_heredada_con_el_nombre_del_slot_o_de_la_sesion_se_llama_como_su_titulo(heredado):
    """Las abiertas antes de C-0479 llevan el `-n` del hub con el renombrado
    apagado, y tmux-resurrect lo conserva al restaurar: sin `dados` seguirían
    saliendo con el nombre del slot."""
    assert tmux.etiqueta_de_ventana(
        heredado, True, "✳ Configs por perfil", "/tmp", "claude",
        {"prototipos", "planos"},
    ) == "Configs por perfil"


@pytest.mark.parametrize("fijo", ["orquestador", "asistente", "agente:revisor", "mantenedor:lienzos"])
def test_una_ventana_vieja_con_un_nombre_fijo_del_hub_se_llama_como_su_titulo(fijo):
    """Las tareas viejas del orquestador salían en «Sin organizar» las cinco
    como «orquestador»: peor que antes del arreglo."""
    assert tmux.etiqueta_de_ventana(fijo, True, "✳ Tarea t-261123", "/tmp", "claude") == "Tarea t-261123"


def test_los_nombres_fijos_del_hub_siguen_siendo_los_de_sus_ventanas():
    from hub import asistente, orquestador
    assert {orquestador.VENTANA, asistente.VENTANA} <= tmux._NOMBRES_DEL_HUB
    import re
    from hub import agentes
    fijos = set(re.findall(r'nombre_ventana="([^"]+)"', open(agentes.__file__, encoding="utf-8").read()))
    assert fijos and fijos <= tmux._NOMBRES_DEL_HUB, fijos - tmux._NOMBRES_DEL_HUB


def test_la_franja_no_da_por_renombrada_una_ventana_con_el_nombre_de_su_slot(monkeypatch):
    """El caso del teléfono, con el listado tal como lo daba tmux."""
    filas = [
        "9\tprototipos\t1\t1\tclaude\t✳ Servidor de pruebas con Forge\t/tmp\t0",
        "10\tplanos\t0\t1\tclaude\t✳ Traspaso de imágenes a planos\t/tmp\t0",
        "11\tlambda SQS\t0\t1\tclaude\t✳ Debugar lambda\t/tmp\t0",
    ]
    monkeypatch.setattr(tmux, "_correr", lambda *a, **k: "\n".join(filas) + "\n")
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)

    ventanas = tmux.listar_ventanas("prototipos", {10: {"planos"}})

    assert [v["etiqueta"] for v in ventanas] == [
        "Servidor de pruebas con Forge", "Traspaso de imágenes a planos", "lambda SQS",
    ]
    assert [v["renombrada"] for v in ventanas] == [False, False, True]


# ── con tmux de verdad ───────────────────────────────────────────────────────

@pytest.fixture
def servidor(monkeypatch):
    """Un servidor de tmux para este test, ni siquiera el de la suite."""
    zocalo = f"nombre-ventana-{os.getpid()}"
    monkeypatch.setenv("HUB_TMUX_SOCKET", zocalo)
    yield
    arnes_tmux.apagar(zocalo)


def _opcion(destino: str, nombre: str) -> str:
    return tmux._correr(["show-options", "-w", "-v", "-t", destino, nombre]).strip()


def _titular(session: str, titulos: dict[int, str]) -> None:
    """El título que pintaría Claude Code, a mano: sin él la etiqueta de una
    shell depende del hostname de quien corre la suite."""
    for v in tmux.listar_ventanas(session):
        if v["indice"] in titulos:
            tmux.escribir_titulo(v["pane_id"], titulos[v["indice"]])


@con_tmux
def test_una_ventana_que_abre_el_hub_con_nombre_se_llama_como_su_titulo(tmp_path, servidor):
    """Las tres primitivas: tmux sigue enseñando el nombre en su barra, pero
    con el renombrado encendido ya no cuenta como puesto a mano."""
    tmux.nueva_sesion("s", str(tmp_path), "primera")
    tmux.abrir_ventana(str(tmp_path), "mi-slot", None, "s")
    tmux.nueva_ventana("s", str(tmp_path), "agente")
    _titular("s", {0: "✳ Uno", 1: "✳ Dos", 2: "✳ Tres"})
    time.sleep(1)   # que el renombrado automático tenga ocasión de actuar

    ventanas = tmux.listar_ventanas("s")
    assert [v["nombre"] for v in ventanas] == ["primera", "mi-slot", "agente"]
    assert [v["etiqueta"] for v in ventanas] == ["Uno", "Dos", "Tres"]
    assert [v["renombrada"] for v in ventanas] == [False, False, False]
    assert {_opcion(f"=s:{i}", "automatic-rename") for i in range(3)} == {"on"}


@con_tmux
def test_un_nombre_con_almohadilla_queda_literal_y_no_ejecuta_nada(tmp_path, servidor):
    """`automatic-rename-format` es un formato: `#(orden)` sin escapar la
    EJECUTA (medido el 24-nov en un servidor aparte). Un nombre de slot viene
    de quien lo escribió, y no puede ser una orden."""
    testigo = tmp_path / "ejecutado"
    nombre = f"#(touch {testigo})##x"
    tmux.nueva_sesion("s", str(tmp_path), nombre)
    tmux.abrir_ventana(str(tmp_path), nombre, None, "s")
    tmux.nueva_ventana("s", str(tmp_path), nombre)
    time.sleep(1.5)

    assert not testigo.exists()
    assert [v["nombre"] for v in tmux.listar_ventanas("s")] == [nombre] * 3


@con_tmux
def test_renombrar_a_mano_cuenta_como_del_dueno(tmp_path, servidor):
    """`rename-window` apaga el renombrado automático: medido, y es lo único
    que hace falta para que el nombre del dueño mande."""
    tmux.nueva_sesion("s", str(tmp_path), "mi-slot")
    _titular("s", {0: "✳ Debugar lambda"})
    assert tmux.listar_ventanas("s")[0]["etiqueta"] == "Debugar lambda"

    tmux.renombrar_ventana("s", 0, "lambda SQS")

    (v,) = tmux.listar_ventanas("s")
    assert v["etiqueta"] == "lambda SQS" and v["renombrada"] is True
    assert _opcion("=s:0", "automatic-rename") == "off"


@con_tmux
def test_un_nombre_que_escribe_el_dueno_al_abrir_cuenta_como_suyo(tmp_path, servidor):
    tmux.nueva_sesion("s", str(tmp_path))
    tmux.nueva_ventana("s", str(tmp_path), "logs", a_mano=True)
    _titular("s", {1: "✳ Otra cosa"})

    assert tmux.listar_ventanas("s")[1]["etiqueta"] == "logs"


# ── la pestaña y el árbol dicen lo mismo ─────────────────────────────────────

@pytest.fixture
def mezcla(con, tmp_path, servidor, monkeypatch):
    """Un slot con cuatro ventanas, como las que hay abiertas hoy:

    0. heredada con el nombre del slot (`-n` de antes de C-0479);
    1. abierta por el hub con el nombre del slot, ya sin fijarlo;
    2. heredada con el nombre de la sesión;
    3. renombrada por el dueño.
    """
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    ruta = str(tmp_path)
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo',?)", (ruta,))
    slot_id = slots.crear(con, "demo", "Hub - Dev", ruta=ruta)
    tmux._correr(["new-session", "-d", "-s", "demo-s", "-n", "Hub - Dev", "-c", ruta])
    tmux.abrir_ventana(ruta, "Hub - Dev", None, "demo-s")
    tmux._correr(["new-window", "-a", "-t", "=demo-s:{end}", "-n", "demo-s", "-c", ruta])
    tmux.abrir_ventana(ruta, "Hub - Dev", None, "demo-s")
    tmux.renombrar_ventana("demo-s", 3, "lambda SQS")
    _titular("demo-s", {0: "✳ Servidor de pruebas", 1: "✳ Traspaso a planos",
                        2: "✳ Configs por perfil", 3: "✳ Debugar lambda"})
    for v in tmux.listar_ventanas("demo-s"):
        slots.vincular(con, v["pane_id"], slot_id)
    atribuidor = Atribuidor([Proyecto(id="demo", nombre="Demo", asiento=ruta)])
    snapshotter.capturar(con, atribuidor)
    return con, slot_id, atribuidor


def _arbol(con, slot_id) -> dict[int, str]:
    ctx = api.contexto_trabajo(con, slot_id)
    (s,) = [s for p in ctx["proyectos"] for s in p["slots"] if s["id"] == slot_id]
    return {v["ventana"]: v["etiqueta"] for v in s["ventanas"]}


def _pestanas(con, slot_id) -> dict[int, str]:
    return {v["indice"]: v["etiqueta"] for v in api.ventanas_de_sesion(con, "demo-s", slot_id)}


@con_tmux
def test_la_pestana_y_el_arbol_nombran_igual_la_misma_ventana(mezcla):
    con, slot_id, _ = mezcla
    esperado = {0: "Servidor de pruebas", 1: "Traspaso a planos",
                2: "Configs por perfil", 3: "lambda SQS"}
    assert _pestanas(con, slot_id) == esperado
    assert _arbol(con, slot_id) == esperado


@con_tmux
def test_renombrar_se_ve_en_el_arbol_tras_el_muestreo(mezcla):
    """Antes el muestreo no miraba el nombre de tmux: lo que renombraba el
    dueño se veía en la franja y en el árbol volvía el título al recargar."""
    con, slot_id, atribuidor = mezcla
    tmux.renombrar_ventana("demo-s", 1, "esquemas")
    snapshotter.capturar(con, atribuidor)

    assert _arbol(con, slot_id)[1] == "esquemas"
    assert _pestanas(con, slot_id)[1] == "esquemas"
