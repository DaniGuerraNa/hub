"""Volver a tener las ventanas delante después de un apagón.

🔴 Este archivo es el que protege el **tercer caso de la regla dura 15**
(decisión 164). La regla prohíbe escribir en un panel de tmux porque su estado
es desconocido, y abre la excepción sólo donde el hub sabe qué hay dentro. Aquí
la condición se cumple porque **crear la ventana y escribir en ella son la misma
operación**: la shell acaba de nacer.

Las dos mitades son inseparables, y la que más fácil se pierde en un refactor es
la segunda: **sin Enter jamás**. Con Enter, «restaurar» pasa de dejar un comando
a la vista a ejecutar siete `claude --dangerously-skip-permissions` sin nadie
delante. Por eso el test que importa no es que abra ventanas: es que no despacha.
"""

from __future__ import annotations

import contextlib
import os
import shutil

import pytest

from hub import restauracion, slots, tmux


@pytest.fixture
def tmux_falso(monkeypatch):
    """Un tmux que anota lo que le piden en vez de hacerlo.

    Se espía y no se ejecuta a propósito: lo que hay que comprobar es **qué
    órdenes** se le dan —sobre todo la que no se le da—, y un tmux de verdad
    diría lo mismo tanto si se manda Enter como si no.
    """
    hecho = {"ventanas": [], "pegados": [], "teclas": []}
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(tmux, "abrir_ventana", lambda ruta, nombre, comando, session: (
        hecho["ventanas"].append({"ruta": ruta, "nombre": nombre,
                                  "comando": comando, "session": session})
        or f"%{len(hecho['ventanas'])}"))
    monkeypatch.setattr(tmux, "escribir_titulo", lambda *a, **k: None)
    monkeypatch.setattr(tmux, "pegar_en_panel", lambda pane, texto, enter=True: (
        hecho["pegados"].append({"pane": pane, "texto": texto, "enter": enter})))
    monkeypatch.setattr(tmux, "tecla_en_panel", lambda pane, tecla: (
        hecho["teclas"].append((pane, tecla))))
    # El panel enseña lo que se le pegó. Sin esto la espera de la regla 17 mira
    # un panel de verdad que no existe — y que el arnés lo note es señal de que
    # la comprobación no es decorativa.
    monkeypatch.setattr(tmux, "capturar_panel", lambda pane, unir_lineas=False: "\n".join(
        f"$ {p['texto']}" for p in hecho["pegados"] if p["pane"] == pane))
    return hecho


@pytest.fixture
def slot_marcado(con, proyecto_demo, tmp_path):
    ruta = tmp_path / "trabajo"
    ruta.mkdir()
    slot_id = slots.crear(con, proyecto_demo, "Lo de siempre", ruta=str(ruta))
    slots.editar(con, slot_id, restaurar=True)
    return slot_id


# ── Lo que la regla dura 15 no permite ───────────────────────────────────────

def test_restaurar_deja_el_comando_escrito_y_NO_lo_lanza(con, slot_marcado, tmux_falso):
    """El test de esta función. Si algún día pasa a `enter=True`, aquí se ve.

    Escribir sin despachar es lo que vuelve inofensivo a «restaurar»: deja el
    comando a la vista para que lo lance una persona, que es el gate humano del
    principio 6.
    """
    slots.restaurar(con)
    assert len(tmux_falso["pegados"]) == 1
    assert tmux_falso["pegados"][0]["enter"] is False, "restaurar despachó el comando"
    assert tmux_falso["teclas"] == [], "restaurar mandó teclas sueltas a un panel"


def test_la_ventana_se_abre_sin_comando_para_que_dentro_haya_una_shell(con, slot_marcado, tmux_falso):
    """Si la ventana naciera ejecutando algo, el pegado iría a parar dentro de
    ese proceso en vez de a un prompt, y el tercer caso de la regla 15 dejaría
    de sostenerse: la ventana ya no sería una shell recién nacida."""
    slots.restaurar(con)
    assert tmux_falso["ventanas"][0]["comando"] is None


def test_el_comando_que_se_deja_escrito_es_uno_que_existe(con, slot_marcado, tmux_falso):
    """Decisión 165: dejar escrito un flag que no existe sería peor que no dejar
    ninguno — hay que borrarlo a mano justo cuando se vuelve de un apagón."""
    slots.restaurar(con)
    assert tmux_falso["pegados"][0]["texto"] == restauracion.COMANDO_SUGERIDO


def test_un_comando_que_se_pega_y_no_aparece_en_pantalla_cuenta_como_fallo(
    con, slot_marcado, tmux_falso, monkeypatch
):
    """🔴 Regla dura 17, del lado que no se despacha.

    La regla nació de un `enviado: true` sobre un mensaje que seguía en
    pantalla. El fallo simétrico es más callado: dar por escrito un comando que
    nunca llegó, y anunciarlo en el panorama justo al volver de un apagón.
    Comprobarlo es una captura, así que no hay excusa para suponerlo.
    """
    monkeypatch.setattr(tmux, "capturar_panel", lambda pane, unir_lineas=False: "$ ")
    monkeypatch.setattr(slots, "SEGUNDOS_PARA_VERLO", 0.2)
    resultado = slots.restaurar(con)
    assert resultado["abiertos"] == []
    assert "no llegó a verse" in resultado["fallos"][0]


def test_si_no_se_puede_dejar_el_comando_no_se_cuenta_como_restaurado(
    con, slot_marcado, tmux_falso, monkeypatch
):
    """Media restauración silenciosa es lo peor: la ventana está y parece que
    salió bien. Se dice cuál falló (regla dura 21)."""
    def revienta(pane, texto, enter=True):
        raise RuntimeError("tmux se cayó a media escritura")

    monkeypatch.setattr(tmux, "pegar_en_panel", revienta)
    resultado = slots.restaurar(con)
    assert resultado["abiertos"] == []
    assert "no se pudo dejar el comando escrito" in resultado["fallos"][0]


# ── Nada automático (regla dura 3) ───────────────────────────────────────────

def test_un_slot_sin_marcar_no_se_restaura(con, proyecto_demo, tmp_path, tmux_falso):
    """La marca es humana y por slot. Restaurar «todo lo que se usó hace poco»
    sería deducirla del uso, que es justo lo que el principio 9 prohíbe."""
    ruta = tmp_path / "otro"
    ruta.mkdir()
    slots.crear(con, proyecto_demo, "Sin marcar", ruta=str(ruta))
    assert slots.restaurar(con)["abiertos"] == []
    assert tmux_falso["ventanas"] == []


def test_un_slot_archivado_no_vuelve_aunque_este_marcado(con, slot_marcado, tmux_falso):
    """Archivar es una decisión humana y restaurar no puede deshacerla."""
    slots.archivar(con, slot_marcado)
    assert slots.restaurar(con)["abiertos"] == []


# ── Que un slot roto no cancele a los demás ──────────────────────────────────

def test_un_slot_sin_ruta_se_salta_y_los_demas_vuelven(
    con, proyecto_demo, slot_marcado, tmux_falso
):
    """Volver de un apagón con seis ventanas menos porque una no tenía ruta
    sería exactamente el momento equivocado para descubrirlo."""
    huerfano = slots.crear(con, proyecto_demo, "Sin sitio")
    slots.editar(con, huerfano, restaurar=True)
    con.execute("UPDATE proyecto SET asiento=NULL WHERE id=?", (proyecto_demo,))

    resultado = slots.restaurar(con)
    assert [a["nombre"] for a in resultado["abiertos"]] == ["Lo de siempre"]
    assert "Sin sitio" in resultado["fallos"][0]


def test_el_boton_de_restaurar_no_toca_docker(con, slot_marcado, tmux_falso, monkeypatch):
    """Decisión 165 y regla dura 12. `docker stop $(docker ps -q)` es un
    accidente documentado: la pantalla de servicios existe para prevenirlo, no
    para reproducirlo desde otro botón."""
    from hub import servicios

    def prohibido(*a, **k):
        raise AssertionError("restaurar llamó a docker")

    monkeypatch.setattr(servicios, "escanear", prohibido)
    monkeypatch.setattr(servicios, "accionar", prohibido, raising=False)
    slots.restaurar(con)


# ── Contra tmux de verdad ────────────────────────────────────────────────────

def test_una_sesion_recien_creada_dice_cual_es_su_panel(tmp_path):
    """🔴 Este test existe porque el otro estaba mockeado, y por eso el fallo
    duró.

    `panel_de_sesion` usaba `display-message -p -t "=sesión" "#{pane_id}"` y
    devolvía una línea VACÍA: con un destino de sesión no hay panel con el que
    resolver el formato. `slots.abrir()` sólo pasa por ahí cuando **no hay
    servidor de tmux** —una instalación recién hecha, decisión 151— así que la
    ventana se abría y parecía funcionar; lo que no ocurría era el `vincular()`
    de después, y el slot se quedaba sin su ventana. Justo el caso que la 151
    existía para arreglar.

    Se ejecuta tmux de verdad a propósito: un doble habría devuelto `"%0"` tan
    contento, que es exactamente lo que pasó.
    """
    if not shutil.which("tmux"):
        pytest.skip("tmux no disponible")
    sesion = f"prueba-panel-{os.getpid()}"
    try:
        tmux.nueva_sesion(sesion, str(tmp_path), "Ventana", None)
        pane_id = tmux.panel_de_sesion(sesion)
        assert pane_id.startswith("%"), f"no devolvió un panel: {pane_id!r}"
    finally:
        with contextlib.suppress(Exception):
            tmux._correr(["kill-session", "-t", f"={sesion}"])


def test_por_omision_deja_escrito_un_claude_que_pide_permisos(monkeypatch):
    """Decisión 266: en la instalación de otra persona no puede quedar, a un
    Enter, un Claude sin permisos que ella no eligió."""
    import importlib
    monkeypatch.delenv("HUB_COMANDO_CLAUDE", raising=False)
    assert importlib.reload(restauracion).COMANDO_SUGERIDO == "claude"

    monkeypatch.setenv("HUB_COMANDO_CLAUDE", "claude --dangerously-skip-permissions")
    assert importlib.reload(restauracion).COMANDO_SUGERIDO == "claude --dangerously-skip-permissions"

    monkeypatch.delenv("HUB_COMANDO_CLAUDE")
    importlib.reload(restauracion)
