"""La fuente de WhatsApp (provisional, decisión 323): lee lo que vuelca el colector.

Se ejecuta de verdad contra archivos en un `HUB_HOME` temporal, escritos con
la misma forma que escribe `componentes/whatsapp-web/colector.js` (su forma la
prueba `pruebas/formato.test.js`, que se lanza aquí también si hay Node). El
colector contra WhatsApp real no se prueba en la suite: exige vincular una
cuenta; su prueba hasta el QR está en el README del componente.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub import config
from hub.secretario import memoria, piezas, servicio
from hub.secretario.fuentes import whatsapp

COMPONENTE = config.RAIZ_REPO / "componentes" / "whatsapp-web"


@pytest.fixture
def carpeta(monkeypatch, tmp_path):
    monkeypatch.setenv("HUB_SECRETARIO_WHATSAPP", str(tmp_path / "secretos"))
    d = whatsapp.carpeta()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _linea(i: int, chat="Ana", texto=None, **extra) -> dict:
    return {"id": f"false_52155{i}@c.us_M{i}", "chat": "5215550001@c.us", "chat_nombre": chat,
            "autor": chat, "autor_id": "5215550001@c.us", "de_mi": False,
            "texto": f"mensaje {i}" if texto is None else texto,
            "hora": f"2026-11-01T08:0{i % 10}:00.000Z", "grupo": False, "tipo": "chat",
            "multimedia": False, "origen": "vivo"} | extra


def _escribir(carpeta: Path, *lineas, crudo: str = "") -> None:
    with (carpeta / "mensajes.jsonl").open("a", encoding="utf-8") as f:
        for l in lineas:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
        f.write(crudo)


def _latido(carpeta: Path, estado="escuchando", hace=timedelta(0), detalle=""):
    cuando = (datetime.now(timezone.utc) - hace).isoformat().replace("+00:00", "Z")
    (carpeta / "estado.json").write_text(json.dumps({"estado": estado, "latido": cuando, "detalle": detalle}))


def test_su_carpeta_cuelga_de_la_del_secretario(monkeypatch, tmp_path):
    """C-0052: la armaba a mano con `HUB_HOME / "secretario"`. Dónde vive lo del
    secretario lo dice `memoria.carpeta()`; dos sitios que deben coincidir
    acaban no coincidiendo."""
    monkeypatch.setattr(memoria, "carpeta", lambda: tmp_path / "otra")
    assert whatsapp.carpeta() == tmp_path / "otra" / "whatsapp"


# ── leer ─────────────────────────────────────────────────────────────────────

def test_lee_lo_nuevo_y_el_cursor_sigue_donde_se_quedo(carpeta):
    _escribir(carpeta, _linea(1), _linea(2))
    eventos, cursor = whatsapp.FUENTE.leer("", {})
    assert [e.texto for e in eventos] == ["mensaje 1", "mensaje 2"]
    assert eventos[0].fuente == "whatsapp" and eventos[0].conversacion == "Ana" and eventos[0].autor == "Ana"
    assert eventos[0].fecha == "2026-11-01T08:01:00.000Z"

    assert whatsapp.FUENTE.leer(cursor, {})[0] == []
    _escribir(carpeta, _linea(3))
    eventos, _ = whatsapp.FUENTE.leer(cursor, {})
    assert [e.texto for e in eventos] == ["mensaje 3"]


def test_solo_estas_y_excluir_se_respetan_como_en_telegram(carpeta):
    _escribir(carpeta, _linea(1, chat="Trabajo"), _linea(2, chat="Familia"), _linea(3, chat="Ana"))
    assert [e.conversacion for e in whatsapp.FUENTE.leer("", {"incluir": ["trabajo"]})[0]] == ["Trabajo"]
    assert [e.conversacion for e in whatsapp.FUENTE.leer("", {"excluir": ["Familia"]})[0]] == ["Trabajo", "Ana"]


def test_una_linea_rota_se_salta_y_las_demas_se_leen(carpeta):
    _escribir(carpeta, _linea(1))
    _escribir(carpeta, crudo='{"id": "roto", "texto": \n[1, 2]\n{"sin_id": true}\n')
    _escribir(carpeta, _linea(2))
    eventos, _ = whatsapp.FUENTE.leer("", {})
    assert [e.texto for e in eventos] == ["mensaje 1", "mensaje 2"]


def test_una_linea_a_medio_escribir_se_deja_para_la_vuelta_siguiente(carpeta):
    entera = json.dumps(_linea(2))
    _escribir(carpeta, _linea(1), crudo=entera[:20])
    eventos, cursor = whatsapp.FUENTE.leer("", {})
    assert [e.texto for e in eventos] == ["mensaje 1"]
    _escribir(carpeta, crudo=entera[20:] + "\n")
    eventos, _ = whatsapp.FUENTE.leer(cursor, {})
    assert [e.texto for e in eventos] == ["mensaje 2"]


def test_si_el_archivo_se_cambia_por_otro_vuelve_a_empezar(carpeta):
    _escribir(carpeta, _linea(1), _linea(2), _linea(3))
    _, cursor = whatsapp.FUENTE.leer("", {})
    (carpeta / "mensajes.jsonl").unlink()
    _escribir(carpeta, _linea(4))
    eventos, _ = whatsapp.FUENTE.leer(cursor, {})
    assert [e.texto for e in eventos] == ["mensaje 4"]


def test_sin_archivo_no_hay_nada_y_un_cursor_estropeado_no_rompe(carpeta):
    assert whatsapp.FUENTE.leer("", {}) == ([], "{}")
    _escribir(carpeta, _linea(1))
    assert len(whatsapp.FUENTE.leer("esto no es json", {})[0]) == 1


def test_la_multimedia_se_anuncia_sin_fingir_que_se_vio(carpeta):
    _escribir(carpeta, _linea(1, texto="la factura", tipo="image", multimedia=True),
              _linea(2, texto="", tipo="ptt", multimedia=True),
              _linea(3, texto="", tipo="chat"))
    assert [e.texto for e in whatsapp.FUENTE.leer("", {})[0]] == [
        "[imagen] la factura", "[nota de voz sin transcribir]"]


def test_estados_y_canales_no_entran_salvo_un_canal_pedido_por_nombre(carpeta):
    _escribir(carpeta, _linea(1, chat="Estados") | {"chat": "status@broadcast"},
              _linea(2, chat="Noticias") | {"chat": "123@newsletter"})
    assert whatsapp.FUENTE.leer("", {})[0] == []
    assert [e.conversacion for e in whatsapp.FUENTE.leer("", {"incluir": ["Noticias"]})[0]] == ["Noticias"]


# ── disponible y conversaciones ──────────────────────────────────────────────

def test_sin_sesion_dice_como_entrar(carpeta):
    assert "entrar" in whatsapp.FUENTE.disponible() and "QR" in whatsapp.FUENTE.disponible()


def test_vinculada_pero_sin_escuchar_dice_que_falta_arrancarlo(carpeta):
    _latido(carpeta, "vinculada")
    assert "escuchar" in whatsapp.FUENTE.disponible()


def test_con_el_colector_parado_dice_desde_cuando(carpeta):
    _latido(carpeta, hace=timedelta(hours=3), detalle="parado a mano")
    falta = whatsapp.FUENTE.disponible()
    assert "no está escribiendo desde hace 3 h" in falta and "parado a mano" in falta and "escuchar" in falta


def test_con_el_latido_al_dia_se_puede_leer(carpeta):
    _latido(carpeta)
    assert whatsapp.FUENTE.disponible() is None


def test_si_whatsapp_cerro_la_sesion_lo_dice(carpeta):
    _latido(carpeta, "sesion-cerrada")
    assert "cerró la sesión" in whatsapp.FUENTE.disponible()


def test_las_conversaciones_salen_de_la_lista_del_colector(carpeta):
    assert whatsapp.FUENTE.conversaciones() == []
    (carpeta / "chats.json").write_text(json.dumps([{"id": "1@g.us", "nombre": "Equipo"}, {"id": "2@c.us", "nombre": "Ana"}]))
    assert whatsapp.FUENTE.conversaciones() == ["Equipo", "Ana"]


# ── en el secretario ─────────────────────────────────────────────────────────

def test_aparece_entre_las_fuentes_y_esta_apagada_por_omision():
    assert "whatsapp" in piezas.fuentes()
    assert not (piezas.ajustes_fuentes().get("whatsapp") or {}).get("activa")


def test_encendida_sus_mensajes_entran_en_la_memoria_una_sola_vez(carpeta):
    piezas.guardar_ajustes_fuentes({"whatsapp": {"activa": True}})
    _latido(carpeta)
    _escribir(carpeta, _linea(1), _linea(2))
    con = memoria.conectar()
    try:
        assert servicio.leer_fuentes(con, forzar=True) == 2
        # El colector puede repetir un mensaje (la recogida al arrancar y el
        # vivo); la memoria lo guarda una vez.
        _escribir(carpeta, _linea(2), _linea(3))
        assert servicio.leer_fuentes(con, forzar=True) == 1
        assert con.execute("SELECT COUNT(*) FROM evento WHERE fuente = 'whatsapp'").fetchone()[0] == 3
    finally:
        con.close()


def test_con_el_colector_parado_el_cursor_espera_y_no_se_pierde_nada(carpeta):
    piezas.guardar_ajustes_fuentes({"whatsapp": {"activa": True}})
    _latido(carpeta, hace=timedelta(hours=1))
    _escribir(carpeta, _linea(1))
    con = memoria.conectar()
    try:
        assert servicio.leer_fuentes(con, forzar=True) == 0
        est = con.execute("SELECT * FROM fuente_estado WHERE fuente = 'whatsapp'").fetchone()
        assert "no está escribiendo" in est["error"]
        _latido(carpeta)
        assert servicio.leer_fuentes(con, forzar=True) == 1
    finally:
        con.close()


# ── el colector ──────────────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="sin Node no se puede ejecutar el colector")
def test_la_forma_de_cada_mensaje_del_colector_se_prueba_ejecutandola():
    # También el lector de la extensión y de la app de escritorio (decisión
    # 331), con Chromium de verdad si está el de Playwright.
    r = subprocess.run(["node", "--test", "pruebas/formato.test.js", "pruebas/lector.test.js"], cwd=COMPONENTE,
                       capture_output=True, text=True, timeout=180, env=os.environ | {"NODE_NO_WARNINGS": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_el_colector_no_llama_a_nada_que_escriba_en_whatsapp():
    """Sólo lectura por construcción: ni enviar, ni marcar leído, ni anunciarse
    disponible. Si algún día hace falta, es otra pieza con su decisión."""
    codigo = (COMPONENTE / "colector.js").read_text(encoding="utf-8")
    # Los comentarios nombran lo que no se hace; lo que cuenta es el código.
    sin_comentarios = "\n".join(l for l in codigo.splitlines() if not l.lstrip().startswith(("*", "//", "/*")))
    for prohibido in ("sendMessage", "sendSeen", "sendPresenceAvailable", "markUnread", "reply(", "react(",
                      "forward(", "sendStateTyping", "archive(", "mute(", "delete("):
        assert prohibido not in sin_comentarios, prohibido
    assert "sendPresenceUnavailable" in sin_comentarios


def test_el_lector_de_la_pagina_no_llama_a_nada_que_escriba_en_whatsapp():
    """El de la extensión y la app (decisión 331) corre DENTRO de WhatsApp Web,
    con acceso a todo: que sólo lea se comprueba en su código."""
    lector = COMPONENTE / "lector"
    codigo = "\n".join((lector / f).read_text(encoding="utf-8") for f in ("pagina.js", "escritorio.js"))
    sin_comentarios = "\n".join(l for l in codigo.splitlines() if not l.lstrip().startswith(("*", "//", "/*")))
    for prohibido in ("sendMessage", "sendSeen", "SendSeen", "markRead", "MarkRead", "sendPresence", "WAWebCmd",
                      "sendText", "addAndSendMsg", "Runtime.enable", "Input.dispatch"):
        assert prohibido not in sin_comentarios, prohibido


# ── los lectores dentro de WhatsApp Web (decisión 331) ───────────────────────

def test_con_un_lector_parado_dice_que_abrir(carpeta):
    (carpeta / "estado.json").write_text(json.dumps({"estado": "parado", "origen": "escritorio",
                                                     "detalle": "la app no está abierta",
                                                     "latido": datetime.now(timezone.utc).isoformat()}))
    assert "app de WhatsApp de Windows" in whatsapp.FUENTE.disponible()


def test_con_un_lector_escuchando_se_puede_leer_sin_sesion_del_colector(carpeta):
    (carpeta / "estado.json").write_text(json.dumps({"estado": "escuchando", "origen": "extension",
                                                     "latido": datetime.now(timezone.utc).isoformat()}))
    assert whatsapp.FUENTE.disponible() is None


def test_comparar_dice_que_vio_cada_lector_y_con_cuanto_retraso(carpeta):
    ahora = datetime.now(timezone.utc)

    def l(i, origen, retraso):
        hora = ahora - timedelta(minutes=10 - i)
        return _linea(i, origen=origen, hora=hora.isoformat(), visto=(hora + timedelta(seconds=retraso)).isoformat())

    _escribir(carpeta, l(1, "extension", 1), l(1, "escritorio", 3), l(2, "extension", 2), l(3, "escritorio", 5),
              _linea(4, origen="extension", hora="2020-01-01T00:00:00Z"))
    c = whatsapp.comparar()
    assert c["mensajes"] == 3
    assert c["por_origen"]["extension"] == {"vistos": 2, "solo_este": 1, "retraso_mediano_s": 2.0}
    assert c["por_origen"]["escritorio"] == {"vistos": 2, "solo_este": 1, "retraso_mediano_s": 5.0}
