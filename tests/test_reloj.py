"""La hora del hub en un solo sitio (C-0051).

Había nueve `ahora()` copiados y dos ideas de hora local. Lo que se fija aquí
es lo que hace que una sola definición sirva a todos: que guarde en UTC y con
zona, y que el módulo siga siendo una hoja que cualquiera puede importar.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub import reloj

SRC = Path(__file__).resolve().parents[1] / "src" / "hub"


def test_ahora_es_utc_al_segundo_y_lleva_su_zona():
    """Sin zona, una fecha se lee como local en un sitio y como UTC en otro."""
    valor = reloj.ahora()
    momento = datetime.fromisoformat(valor)

    assert valor.endswith("+00:00")
    assert momento.microsecond == 0
    assert abs(datetime.now(timezone.utc) - momento) < timedelta(seconds=5)


def test_reloj_es_una_hoja_que_no_importa_nada_del_hub():
    """🔴 `maquina` tenía su copia porque importar la de `snapshotter` cerraba un
    círculo. Si `reloj` importa algo del hub, el círculo vuelve."""
    arbol = ast.parse((SRC / "reloj.py").read_text(encoding="utf-8"))
    del_hub = [ast.unparse(n) for n in ast.walk(arbol)
               if isinstance(n, ast.ImportFrom) and (n.level or (n.module or "").startswith("hub"))]
    del_hub += [ast.unparse(n) for n in ast.walk(arbol)
                if isinstance(n, ast.Import) and any(a.name.startswith("hub") for a in n.names)]

    assert del_hub == []


def test_los_modulos_que_tenian_su_copia_usan_la_de_reloj():
    from hub import avisos, buzon, encargos, maquina, orquestador, programados, rele_encargos, snapshotter
    from hub.secretario import memoria

    for modulo in (avisos, buzon, encargos, maquina, orquestador, programados,
                   snapshotter, memoria):
        assert modulo.ahora is reloj.ahora, modulo.__name__
    # `rele_encargos` sólo la usaba para leer fechas: ahora lee con `instante` (C-0186).
    assert rele_encargos.instante is reloj.instante


# ── La zona de la máquina (pieza b) ─────────────────────────────────────────
#
# 🔴 Sin `TZ` ni `/etc/timezone` —Fedora, Arch: sólo el enlace de
# `/etc/localtime`— el secretario caía a UTC y recordaba a otra hora,
# mientras `api` enseñaba la hora bien porque miraba `/etc/localtime`. Las
# rutas se cambian en el módulo: nada de esto toca la máquina.


@pytest.fixture
def maquina(monkeypatch, tmp_path):
    """Una máquina sin TZ, sin `/etc/timezone` y sin `/etc/localtime`."""
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(reloj, "ETC_TIMEZONE", tmp_path / "no-hay-timezone")
    monkeypatch.setattr(reloj, "ETC_LOCALTIME", tmp_path / "no-hay-localtime")
    return tmp_path


def _enlazar_localtime(monkeypatch, raiz: Path, zona: str) -> None:
    """`/etc/localtime` como lo deja timedatectl: un enlace a `…/zoneinfo/<zona>`."""
    destino = raiz / "usr" / "share" / "zoneinfo" / zona
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(b"TZif")
    enlace = raiz / "localtime"
    enlace.symlink_to(destino)
    monkeypatch.setattr(reloj, "ETC_LOCALTIME", enlace)


def test_sin_tz_ni_etc_timezone_la_zona_sale_del_enlace_de_localtime(maquina, monkeypatch):
    _enlazar_localtime(monkeypatch, maquina, "Europe/Madrid")

    assert reloj.zona() == "Europe/Madrid"


def test_el_secretario_ya_no_cae_a_utc_sin_etc_timezone(maquina, monkeypatch):
    """El fallo real para el producto: un recordatorio a las 10 de Madrid."""
    from hub.secretario import tiempo

    _enlazar_localtime(monkeypatch, maquina, "Europe/Madrid")

    assert tiempo.zona() == "Europe/Madrid"
    assert tiempo.a_utc("2026-07-01T10:00") == "2026-07-01T08:00:00+00:00"


def test_tz_manda_sobre_los_archivos(maquina, monkeypatch):
    (maquina / "timezone").write_text("Europe/Madrid\n")
    monkeypatch.setattr(reloj, "ETC_TIMEZONE", maquina / "timezone")
    monkeypatch.setenv("TZ", "Asia/Tokyo")

    assert reloj.zona() == "Asia/Tokyo"


def test_etc_timezone_va_antes_que_el_enlace(maquina, monkeypatch):
    (maquina / "timezone").write_text("America/Mexico_City\n")
    monkeypatch.setattr(reloj, "ETC_TIMEZONE", maquina / "timezone")
    _enlazar_localtime(monkeypatch, maquina, "Europe/Madrid")

    assert reloj.zona() == "America/Mexico_City"


def test_una_tz_que_no_es_una_zona_no_tumba_nada_y_se_sigue_buscando(maquina, monkeypatch):
    """`ZoneInfo` de algo que no existe lanza, y eso rompía cada página que
    enseña una hora. Mejor la siguiente fuente que una excepción."""
    monkeypatch.setenv("TZ", "Nada/Falsa")
    _enlazar_localtime(monkeypatch, maquina, "Europe/Madrid")

    assert reloj.zona() == "Europe/Madrid"


def test_el_enlace_a_la_copia_posix_da_la_zona_de_siempre(maquina, monkeypatch):
    _enlazar_localtime(monkeypatch, maquina, "posix/Europe/Madrid")

    assert reloj.zona() == "Europe/Madrid"


def test_sin_ninguna_fuente_es_utc(maquina):
    assert reloj.zona() == "UTC"


def test_un_localtime_copiado_y_no_enlazado_no_dice_su_zona(maquina, monkeypatch):
    """Algunas imágenes copian el archivo en vez de enlazarlo: de ahí no se
    sabe el nombre de la zona, y se dice UTC antes que adivinar."""
    (maquina / "localtime").write_bytes(b"TZif")
    monkeypatch.setattr(reloj, "ETC_LOCALTIME", maquina / "localtime")

    assert reloj.zona() == "UTC"


# ── Enseñar una hora ────────────────────────────────────────────────────────


def test_a_local_pasa_de_utc_a_la_hora_de_la_casa_con_el_formato_que_se_pida(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")

    assert reloj.a_local("2026-10-26T16:00:00+00:00") == "2026-10-26 10:00"
    assert reloj.a_local("2026-10-26T16:00:00+00:00", "%d/%m %H:%M") == "26/10 10:00"


def test_a_local_sin_fecha_no_dice_nada_y_lo_que_no_es_fecha_sale_tal_cual(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")

    assert reloj.a_local(None) == ""
    assert reloj.a_local("") == ""
    assert reloj.a_local("ayer") == "ayer"


def test_una_hora_sin_zona_ya_es_hora_local_como_al_guardarla(monkeypatch):
    """Lo mismo que `tiempo.a_utc` hace al revés: lo que no dice su zona es
    de la casa. Antes se leía como hora de la máquina, que aquí es lo mismo."""
    monkeypatch.setenv("TZ", "America/Mexico_City")

    assert reloj.a_local("2026-10-26T10:00") == "2026-10-26 10:00"


def test_la_web_enseña_la_hora_en_la_misma_zona_que_el_secretario(monkeypatch):
    """`api._hora_local` miraba `/etc/localtime` por su cuenta; ahora pregunta
    a `reloj.zona`, y una hora no puede salir distinta en dos pantallas."""
    from hub import api

    monkeypatch.setenv("TZ", "Asia/Tokyo")

    # El año sólo sale si no es el de ahora: el día y la hora, siempre.
    assert re.fullmatch(r"27/10(/2026)? 01:00", api._hora_local("2026-10-26T16:00:00+00:00"))


def test_el_secretario_y_la_web_usan_la_misma_zona_y_la_misma_conversion():
    from hub.secretario import tiempo

    assert tiempo.zona is reloj.zona
    assert tiempo.a_local is reloj.a_local


def test_una_fecha_guardada_sin_zona_se_lee_como_utc_y_se_puede_comparar():
    """C-0186: comparar una fecha sin zona con una con zona lanza, y donde se
    compara —la puerta de las reentregas— es en mitad de tratar un mensaje.
    Lo guardado sin zona es UTC, como guarda `ahora()`; lo que se ENSEÑA es
    otra cosa (`a_local`, 375)."""
    sin_zona = reloj.instante("2026-11-06T10:00:00")
    con_zona = reloj.instante("2026-11-06T10:00:00+00:00")

    assert sin_zona == con_zona and sin_zona.tzinfo is not None
    assert reloj.instante() - con_zona > timedelta(0)
    assert abs(reloj.instante(None) - datetime.now(timezone.utc)) < timedelta(seconds=5)


# ── Un instante, de una sola forma (C-0396) ─────────────────────────────────
#
# Había ocho formatos de fecha en las pantallas y la mitad en UTC. `cuando` da
# las piezas —local, «hace», edad— y `ui.cuando` las pinta: lo que se fija aquí
# es que «hace» y «local» salgan del MISMO instante, también sin zona.

#: Las 14:41 en la casa (UTC-6 todo el año desde 2022).
AHORA = datetime(2026, 11, 13, 20, 41, tzinfo=timezone.utc)


@pytest.fixture
def casa(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")


def test_cuando_pasa_de_utc_a_la_casa_y_dice_cuanto_hace(casa):
    c = reloj.cuando("2026-11-13T17:41:00+00:00", AHORA)

    assert c == {"iso": "2026-11-13T11:41:00-06:00", "local": "13/11 11:41", "dia": "13/11",
                 "hora": "11:41", "hace": "hace 3 h", "edad_s": 10800}


def test_cuando_lee_una_hora_sin_zona_como_hora_de_la_casa_igual_que_a_local(casa):
    """🔴 Regla 19: con `instante` (sin zona = UTC) el «hace» y el «local» de
    la misma fecha discreparían seis horas. Las dos salen del mismo lector."""
    sin_zona = "2026-11-13T11:41:00"

    c = reloj.cuando(sin_zona, AHORA)

    assert c["local"] == reloj.a_local(sin_zona, "%d/%m %H:%M") == "13/11 11:41"
    assert c["hace"] == "hace 3 h" and c["edad_s"] == 10800


def test_cuando_de_algo_que_vendra_dice_en_y_su_edad_es_negativa(casa):
    c = reloj.cuando("2026-11-15T20:41:00+00:00", AHORA)

    assert c["hace"] == "en 2 d" and c["edad_s"] == -172800


def test_cuando_no_baja_de_hace_un_momento_para_no_repintar_a_cada_sondeo(casa):
    assert reloj.cuando("2026-11-13T20:40:31+00:00", AHORA)["hace"] == "hace un momento"
    assert reloj.cuando("2026-11-13T20:39:30+00:00", AHORA)["hace"] == "hace 1 min"
    assert reloj.cuando(AHORA.timestamp() - 30, AHORA)["hace"] == "hace un momento"


def test_cuando_de_una_fecha_sin_hora_dice_hoy_o_ayer_y_no_inventa_la_hora(casa):
    assert reloj.cuando("2026-11-13", AHORA)["hace"] == "hoy"
    assert reloj.cuando("2026-11-12", AHORA)["hace"] == "ayer"
    assert reloj.cuando("2026-11-14", AHORA)["hace"] == "mañana"
    c = reloj.cuando("2026-11-03", AHORA)
    assert (c["local"], c["dia"], c["hora"], c["hace"], c["iso"]) == ("03/11", "03/11", "", "hace 10 d", "2026-11-03")


def test_cuando_lleva_el_ano_solo_si_no_es_el_actual(casa):
    c = reloj.cuando("2025-11-13T17:41:00+00:00", AHORA)

    assert (c["local"], c["dia"]) == ("13/11/2025 11:41", "13/11/2025")


def test_cuando_de_lo_que_no_es_una_fecha_no_devuelve_nada(casa):
    for basura in (None, "", "ayer", "2026-13-45", True, object()):
        assert reloj.cuando(basura, AHORA) is None, basura


def test_la_duracion_cambia_de_unidad_en_sus_cortes():
    cortes = {0: "0 s", 40: "40 s", 119: "119 s", 120: "2 min", 7199: "119 min",
              7200: "2 h", 172799: "47 h", 172800: "2 d", 9 * 86400: "9 d"}

    assert {s: reloj.duracion(s) for s in cortes} == cortes


def test_las_dos_copias_de_hace_usan_la_duracion_de_reloj():
    """`salud` y la fuente de WhatsApp tenían su `_hace`, con cortes distintos:
    «120 h» en una y «5 días» en la otra para el mismo lapso."""
    from hub import salud
    from hub.secretario.fuentes import whatsapp

    for modulo in (salud, whatsapp):
        assert not hasattr(modulo, "_hace"), modulo.__name__
        assert "reloj.duracion(" in Path(modulo.__file__).read_text(encoding="utf-8"), modulo.__name__
