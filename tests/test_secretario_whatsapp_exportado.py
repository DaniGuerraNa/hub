"""Chats de WhatsApp exportados a mano (decisión 326): los formatos que salen
de un teléfono de verdad, ejecutados contra la fuente con archivos en disco."""
from __future__ import annotations

import json
import zipfile

import pytest

from hub.secretario.fuentes import whatsapp_exportado as wx

ANDROID = """1/11/26, 10:15 - Los mensajes y las llamadas están cifrados de extremo a extremo.
1/11/26, 10:15 - Ana López: ¿Mandas el reporte de lambdas el viernes?
1/11/26, 10:17 - Leo: Sí, lo mando el viernes
y de paso reviso los permisos
13/11/26, 21:05 - Ana López: <Multimedia omitido>
"""
IPHONE_12H = """[01/11/2026, 10:15:30 a. m.] Ana: hola
[01/11/2026, 12:05:00 p. m.] Ana: ¿comemos?
[01/11/2026, 12:30:00 a. m.] Ana: perdón, era medianoche
"""


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    monkeypatch.setenv("TZ", "America/Mexico_City")
    d = wx.carpeta()
    d.mkdir(parents=True)
    return d


def test_su_carpeta_cuelga_de_la_del_secretario(monkeypatch, tmp_path):
    """C-0052: la armaba a mano con `HUB_HOME / "secretario"` en vez de
    preguntársela a `memoria.carpeta()`."""
    from hub.secretario import memoria

    monkeypatch.setattr(memoria, "carpeta", lambda: tmp_path / "otra")
    assert wx.carpeta() == tmp_path / "otra" / "whatsapp-exportado"


def test_android_en_espanol_une_las_lineas_salta_el_sistema_y_marca_lo_no_exportado():
    m = wx.mensajes(ANDROID)
    assert [x["autor"] for x in m] == ["Ana López", "Leo", "Ana López"]
    assert m[1]["texto"] == "Sí, lo mando el viernes\ny de paso reviso los permisos"
    assert m[0]["fecha"] == "2026-11-01T10:15"
    # 13/11 dice que el orden es día/mes.
    assert m[2]["fecha"] == "2026-11-13T21:05" and m[2]["texto"] == "[adjunto no exportado]"


def test_iphone_con_hora_de_doce_horas_y_espacios_raros():
    m = wx.mensajes(IPHONE_12H)
    assert [x["fecha"] for x in m] == ["2026-11-01T10:15", "2026-11-01T12:05", "2026-11-01T00:30"]


def test_el_orden_mes_dia_se_deduce_o_se_fuerza():
    assert wx.mensajes("11/13/26, 9:00 - Ana: hola")[0]["fecha"] == "2026-11-13T09:00"
    assert wx.mensajes("3/4/26, 9:00 - Ana: hola", "mdy")[0]["fecha"] == "2026-03-04T09:00"
    assert wx.mensajes("3/4/26, 9:00 - Ana: hola")[0]["fecha"] == "2026-04-03T09:00"


def test_la_fuente_lee_txt_y_zip_una_vez_y_el_dueno_es_yo(carpeta):
    (carpeta / "Chat de WhatsApp con Ana López.txt").write_text(ANDROID, encoding="utf-8")
    with zipfile.ZipFile(carpeta / "WhatsApp Chat with Equipo.zip", "w") as z:
        z.writestr("_chat.txt", IPHONE_12H)
    assert wx.FUENTE.disponible() is None
    assert wx.FUENTE.conversaciones() == ["Ana López", "Equipo"]
    eventos, cursor = wx.FUENTE.leer("", {"yo": ["Leo"]})
    por_chat = {}
    for e in eventos:
        por_chat.setdefault(e.conversacion, []).append(e)
    assert len(por_chat["Ana López"]) == 3 and len(por_chat["Equipo"]) == 3
    assert por_chat["Ana López"][1].autor == "Yo"
    assert por_chat["Ana López"][0].fecha == "2026-11-01T16:15:00+00:00"
    assert wx.FUENTE.leer(cursor, {"yo": ["Leo"]})[0] == []


def test_exportar_otra_vez_el_mismo_chat_da_los_mismos_ids(carpeta):
    ruta = carpeta / "Chat de WhatsApp con Ana.txt"
    ruta.write_text(ANDROID, encoding="utf-8")
    primeros, cursor = wx.FUENTE.leer("", {})
    ruta.write_text(ANDROID + "14/11/26, 08:00 - Ana: ¿y?\n", encoding="utf-8")
    segundos, _ = wx.FUENTE.leer(json.dumps({}), {})
    viejos = {e.id_externo for e in primeros}
    nuevos = [e for e in segundos if e.id_externo not in viejos]
    assert [e.texto for e in nuevos] == ["¿y?"]


def test_solo_estas_conversaciones(carpeta):
    (carpeta / "Chat de WhatsApp con Ana.txt").write_text(ANDROID, encoding="utf-8")
    (carpeta / "Chat de WhatsApp con Familia.txt").write_text(ANDROID, encoding="utf-8")
    eventos, _ = wx.FUENTE.leer("", {"incluir": ["Familia"]})
    assert {e.conversacion for e in eventos} == {"Familia"}


def test_sin_exportaciones_dice_como_sacarlas(carpeta):
    assert "Exportar chat" in wx.FUENTE.disponible()


def test_sin_ajuste_yo_vale_el_nombre_del_dueno_de_secretario_yml(carpeta):
    (carpeta.parent / "secretario.yml").write_text("dueno: Leo\n", encoding="utf-8")
    (carpeta / "Chat de WhatsApp con Ana.txt").write_text(ANDROID, encoding="utf-8")
    eventos, _ = wx.FUENTE.leer("", {})
    assert [e.autor for e in eventos] == ["Ana López", "Yo", "Ana López"]
