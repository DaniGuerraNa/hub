"""Gestión de ventanas desde la UI.

La regla que gobierna este módulo: **navegar** actúa sobre el espejo, **modificar**
actúa sobre la sesión real. Moverte por la UI no puede arrastrar de ventana a
quien esté atacado en la terminal nativa.
"""

from __future__ import annotations

import pytest

from hub import tmux

LISTADO = "\t".join(["0", "back", "1", "1", "claude", "⠂ Motor fiscal", "/tmp/a"]) + "\n" + \
          "\t".join(["1", "bash", "0", "2", "bash", "DESKTOP", "/tmp/b"])


@pytest.fixture
def registro(monkeypatch):
    llamadas = []

    def falso(args):
        llamadas.append(args)
        return LISTADO if args[0] == "list-windows" else ""

    monkeypatch.setattr(tmux, "_correr", falso)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    # El listado lleva DESKTOP como el título que tmux pone solo (el hostname):
    # sin fijarlo, la prueba sólo pasaba en una máquina que se llamara así.
    monkeypatch.setattr(tmux, "_titulo_por_defecto", lambda: {"desktop"})
    return llamadas


def test_lista_ventanas_con_su_etiqueta(registro):
    ventanas = tmux.listar_ventanas("work")
    assert [v["indice"] for v in ventanas] == [0, 1]
    assert ventanas[0]["activa"] is True
    assert ventanas[0]["etiqueta"] == "Motor fiscal"
    # Un panel sin título propio se compone con la carpeta.
    assert ventanas[1]["etiqueta"] == "b"
    assert ventanas[1]["paneles"] == 2


def test_seleccionar_actua_sobre_el_destino_que_se_le_da(registro):
    """La vista pasa el ESPEJO, nunca la sesión real."""
    tmux.seleccionar_ventana("hub-work-abc123", 2)
    assert ["select-window", "-t", "=hub-work-abc123:2"] in registro


def test_crear_ventana_usa_la_ruta_del_slot(registro):
    """`-P -F` devuelve el índice: sin él no se puede navegar a lo recién creado."""
    tmux.nueva_ventana("work", "/tmp/demo", "investigación")
    assert registro[-1] == [
        "new-window", "-P", "-F", "#{window_index}",
        "-a", "-t", "=work:{end}", "-c", "/tmp/demo", "-n", "investigación",
    ]


def test_crear_ventana_con_comando_lo_pone_al_final(registro):
    tmux.nueva_ventana("work", "/tmp/demo", "agente", "claude 'hola'")
    assert registro[-1][-1] == "claude 'hola'"


def test_renombrar_apunta_a_la_sesion_real(registro):
    tmux.renombrar_ventana("work", 1, "logs")
    assert registro[-1] == ["rename-window", "-t", "=work:1", "logs"]


def test_cerrar_apunta_al_panel_y_no_al_indice(registro, monkeypatch):
    """Decisión 396: `kill-window -t %N` mata la ventana de ese panel."""
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 42)
    assert tmux.cerrar_ventana_de("%7", 42) is True
    assert registro[-1] == ["kill-window", "-t", "%7"]


def test_con_el_servidor_de_otro_muestreo_no_se_cierra_nada(registro, monkeypatch):
    """Los `%N` se reutilizan al reiniciar tmux."""
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 43)
    for servidor in (42, None, "", "x"):
        with pytest.raises(tmux.ServidorDistinto):
            tmux.cerrar_ventana_de("%7", servidor)
    assert registro == []


@pytest.mark.parametrize("malicioso", ["work; kill-server", "$(whoami)", "a b", "../x"])
def test_ninguna_operacion_acepta_un_destino_inventado(malicioso, registro):
    for operacion in (
        lambda: tmux.listar_ventanas(malicioso),
        lambda: tmux.nueva_ventana(malicioso),
        lambda: tmux.renombrar_ventana(malicioso, 0, "x"),
        lambda: tmux.cerrar_ventana_de(malicioso, 1),
        lambda: tmux.seleccionar_ventana(malicioso, 0),
    ):
        with pytest.raises(tmux.DestinoInvalido):
            operacion()
    assert registro == [], "no debe haber llegado nada a tmux"


def test_el_indice_siempre_se_convierte_a_entero(registro):
    """Aunque llegue como texto desde la URL, nunca se interpola en crudo."""
    tmux.renombrar_ventana("work", "3", "x")
    assert registro[-1] == ["rename-window", "-t", "=work:3", "x"]

    with pytest.raises(ValueError):
        tmux.renombrar_ventana("work", "3; kill-server", "x")


# --------------------------------------------------------------------------- #
# Un nombre puesto a mano manda sobre el título de Claude Code
# --------------------------------------------------------------------------- #


def _ventanas_falsas(monkeypatch, filas):
    monkeypatch.setattr(tmux, "_correr", lambda *a, **k: "\n".join(filas) + "\n")
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)


def test_una_ventana_renombrada_a_mano_enseña_su_nombre(monkeypatch):
    """🔴 Renombrar guardaba bien el nombre en tmux y la pestaña seguía pintando
    `pane_title`, que Claude Code reescribe cada pocos segundos. El renombrado
    funcionaba y parecía roto, que es la peor combinación posible.

    `automatic-rename` a 0 es el discriminador: verificado contra tmux, un
    `rename-window` lo apaga solo."""
    _ventanas_falsas(monkeypatch, [
        "1\tlambda SQS\t1\t1\tclaude\t✳ Debugar lambda de notificaciones\t/tmp\t0",
    ])
    v = tmux.listar_ventanas("work")[0]
    assert v["etiqueta"] == "lambda SQS"
    assert v["renombrada"] is True


def test_sin_renombrar_manda_el_titulo_que_claude_escribe(monkeypatch):
    """Es el caso normal y el que hace útiles las pestañas sin tocar nada."""
    _ventanas_falsas(monkeypatch, [
        "0\tclaude\t1\t1\tclaude\t✳ Replicar estructura de mensajes\t/tmp\t1",
    ])
    v = tmux.listar_ventanas("work")[0]
    assert v["etiqueta"] == "Replicar estructura de mensajes"
    assert v["renombrada"] is False


def test_un_tmux_sin_el_campo_no_revienta(monkeypatch):
    """Formato viejo, sin `automatic-rename`: se asume automático, que es el
    caso común, en vez de dejar de listar ventanas."""
    _ventanas_falsas(monkeypatch, [
        "0\tclaude\t1\t1\tclaude\t✳ Algo\t/tmp",
    ])
    v = tmux.listar_ventanas("work")[0]
    assert v["etiqueta"] == "Algo" and v["renombrada"] is False


def test_la_ventana_reporta_su_ancho_real(monkeypatch):
    """🔴 El desfase entre las columnas de tmux y las del navegador **borra
    texto sin avisar**: tmux escribe hasta su última columna y el navegador sólo
    pinta hasta la suya, así que las letras de en medio no aparecen en ninguna
    parte. Costó tres intentos encontrarlo justamente porque no se veía."""
    _ventanas_falsas(monkeypatch, [
        "0\tclaude\t1\t1\tclaude\t✳ Algo\t/tmp\t1\t168",
    ])
    assert tmux.listar_ventanas("work")[0]["ancho"] == 168


def test_sin_el_campo_de_ancho_no_se_inventa_un_numero(monkeypatch):
    """Regla dura 13: la vista prefiere no comparar a comparar contra un cero."""
    _ventanas_falsas(monkeypatch, [
        "0\tclaude\t1\t1\tclaude\t✳ Algo\t/tmp\t1",
    ])
    assert tmux.listar_ventanas("work")[0]["ancho"] is None


def test_una_ventana_sin_ruta_se_abre_donde_esta_la_sesion(registro):
    """🔴 Sin `-c`, tmux hereda el cwd de quien creó la SESIÓN, y todo lo que
    abre el hub lo crea `hub-web` —bajo systemd, desde el directorio del hub—.
    El botón «nueva ventana» daba una shell en el código del hub en vez de en el
    proyecto, y en la pantalla no había nada que lo explicara.

    `#{pane_current_path}` es el idioma de tmux para «aquí mismo»: lo resuelve
    él contra el destino, sin una consulta extra que pueda quedarse vieja.
    """
    tmux.nueva_ventana("work")
    assert registro[-1][-2:] == ["-c", "#{pane_current_path}"]


def test_con_ruta_manda_la_ruta_y_no_el_formato(registro):
    tmux.nueva_ventana("work", "/tmp/demo")
    assert registro[-1][-2:] == ["-c", "/tmp/demo"]


def test_una_ventana_nueva_va_detras_de_la_ultima_aunque_haya_un_hueco(tmp_path):
    """🔴 21-oct: tras cerrar una, tmux le daba a la siguiente el número libre
    más bajo y quedaba a media lista. Con tmux de verdad (servidor de tests)."""
    sesion = "al-final-prueba"
    tmux._correr(["new-session", "-d", "-s", sesion, "-c", str(tmp_path)])
    try:
        tmux.nueva_ventana(sesion, str(tmp_path), "b")
        tmux.nueva_ventana(sesion, str(tmp_path), "c")
        tmux._correr(["kill-window", "-t", f"={sesion}:1"])

        tmux.nueva_ventana(sesion, str(tmp_path), "d")
        tmux.abrir_ventana(str(tmp_path), "e", None, sesion)

        nombres = [v["nombre"] for v in tmux.listar_ventanas(sesion)]
        assert nombres[-2:] == ["d", "e"]
        assert [v["indice"] for v in tmux.listar_ventanas(sesion)][1:] == [2, 3, 4]
    finally:
        tmux._correr(["kill-session", "-t", f"={sesion}"])


def test_cerrar_por_el_panel_con_tmux_de_verdad(tmp_path, monkeypatch):
    """Con un servidor propio: la ventana del panel muere, las otras no, y el
    segundo clic dice «ya estaba cerrada» en vez de matar otra (C-0227)."""
    monkeypatch.setenv("HUB_TMUX_SOCKET", f"cerrar-panel-{tmp_path.name}"[:60])
    sesion = "cerrar-prueba"
    tmux._correr(["new-session", "-d", "-s", sesion, "-n", "a", "-c", str(tmp_path)])
    try:
        tmux.nueva_ventana(sesion, str(tmp_path), "b")
        tmux.nueva_ventana(sesion, str(tmp_path), "c")
        ventanas = tmux.listar_ventanas(sesion)
        b = next(v for v in ventanas if v["nombre"] == "b")
        assert b["pane_id"].startswith("%") and b["servidor"] == tmux.servidor_pid()

        assert tmux.cerrar_ventana_de(b["pane_id"], b["servidor"]) is True
        assert [v["nombre"] for v in tmux.listar_ventanas(sesion)] == ["a", "c"]

        # tmux da a la siguiente el número libre: «b» ya no está, pero su `%N` no es de nadie.
        tmux._correr(["new-window", "-d", "-t", f"={sesion}:{b['indice']}", "-n", "d"])
        assert tmux.cerrar_ventana_de(b["pane_id"], b["servidor"]) is False
        assert [v["nombre"] for v in tmux.listar_ventanas(sesion)] == ["a", "d", "c"]
    finally:
        tmux._correr(["kill-server"])


def test_cerrar_la_ultima_ventana_no_se_anuncia_como_una_sesion_perdida(tmp_path, monkeypatch):
    """La última ventana se lleva el servidor de tmux, y el muestreo lo toma
    por una caída: «se perdió una sesión» por algo que se cerró a propósito
    (arquitecto, C-0227). Con tmux de verdad en su propio servidor."""
    from hub import api, snapshotter, web

    monkeypatch.setenv("HUB_TMUX_SOCKET", f"cerrar-ultima-{tmp_path.name}"[:60])
    tmux._correr(["new-session", "-d", "-s", "sola", "-c", str(tmp_path)])
    try:
        con = web.conexion()
        snapshotter.un_ciclo(con)
        panel = api.paneles_abiertos(con)[0]
        servidor = api.snapshot_actual(con)["server_pid"]

        assert web._cerrar_ventana(panel["pane_id"], servidor) == (True, "")

        assert tmux.servidor_pid() is None
        assert api.paneles_abiertos(con) == []
        assert api.recuperacion_pendiente(con) is None
        # Y sigue así en la vuelta siguiente del demonio, con tmux apagado: la
        # volvía a marcar como perdida a los 20 s (revisor).
        snapshotter.un_ciclo(con)
        assert api.recuperacion_pendiente(con) is None
        con.close()
    finally:
        try:
            tmux._correr(["kill-server"])
        except (tmux.TmuxNoDisponible, RuntimeError):
            pass
