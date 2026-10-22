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


def test_renombrar_y_cerrar_apuntan_a_la_sesion_real(registro):
    tmux.renombrar_ventana("work", 1, "logs")
    assert registro[-1] == ["rename-window", "-t", "=work:1", "logs"]

    tmux.cerrar_ventana("work", 1)
    assert registro[-1] == ["kill-window", "-t", "=work:1"]


@pytest.mark.parametrize("malicioso", ["work; kill-server", "$(whoami)", "a b", "../x"])
def test_ninguna_operacion_acepta_un_destino_inventado(malicioso, registro):
    for operacion in (
        lambda: tmux.listar_ventanas(malicioso),
        lambda: tmux.nueva_ventana(malicioso),
        lambda: tmux.renombrar_ventana(malicioso, 0, "x"),
        lambda: tmux.cerrar_ventana(malicioso, 0),
        lambda: tmux.seleccionar_ventana(malicioso, 0),
    ):
        with pytest.raises(tmux.DestinoInvalido):
            operacion()
    assert registro == [], "no debe haber llegado nada a tmux"


def test_el_indice_siempre_se_convierte_a_entero(registro):
    """Aunque llegue como texto desde la URL, nunca se interpola en crudo."""
    tmux.cerrar_ventana("work", "3")
    assert registro[-1] == ["kill-window", "-t", "=work:3"]

    with pytest.raises(ValueError):
        tmux.cerrar_ventana("work", "3; kill-server")


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
        tmux.cerrar_ventana(sesion, 1)

        tmux.nueva_ventana(sesion, str(tmp_path), "d")
        tmux.abrir_ventana(str(tmp_path), "e", None, sesion)

        nombres = [v["nombre"] for v in tmux.listar_ventanas(sesion)]
        assert nombres[-2:] == ["d", "e"]
        assert [v["indice"] for v in tmux.listar_ventanas(sesion)][1:] == [2, 3, 4]
    finally:
        tmux._correr(["kill-session", "-t", f"={sesion}"])
