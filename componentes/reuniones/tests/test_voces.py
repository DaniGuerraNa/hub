"""Quién habla en la pista de la reunión, y sus nombres.

La asignación y los nombres se prueban con datos; pyannote, con audio real de
la reunión grabada (sólo si el modelo ya está descargado: no se baja nada en
un test).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reuniones import procesar, voces

T = lambda ini, fin, voz: {"ini": ini, "fin": fin, "voz": voz}


def test_cada_intervencion_es_de_la_voz_que_mas_habla_en_ella_y_se_numeran_por_orden():
    segs = [{"ini": 0, "fin": 4, "texto": "Buenos días", "quien": "Reunión"},
            {"ini": 5, "fin": 9, "texto": "Yo me encargo", "quien": "Yo"},
            {"ini": 10, "fin": 14, "texto": "Lo veo el lunes", "quien": "Reunión"},
            {"ini": 20, "fin": 22, "texto": "¿Se me oye?", "quien": "Reunión"},
            {"ini": 30, "fin": 31, "texto": "(ruido)", "quien": "Reunión"}]
    turnos = [T(0, 3.5, "SPEAKER_07"), T(3.5, 4, "SPEAKER_02"),
              T(10, 11, "SPEAKER_07"), T(11, 14, "SPEAKER_02"), T(20, 22, "SPEAKER_07"),
              T(5, 9, "SPEAKER_02")]   # tu voz también suena en la pista: no te la quita

    quien = [s["quien"] for s in voces.asignar(segs, turnos)]

    assert quien == ["Persona 1", "Yo", "Persona 2", "Persona 1", "Reunión"]


def test_los_nombres_se_guardan_al_lado_y_uno_vacio_quita_el_que_habia(tmp_path):
    voces.poner_nombres(tmp_path, {"Persona 1": "  Ana  López ", "Persona 2": "Luis",
                                   "Yo": "no se toca", "../x": "tampoco"})
    voces.poner_nombres(tmp_path, {"Persona 2": ""})

    assert voces.nombres(tmp_path) == {"Persona 1": "Ana López"}
    segs = voces.con_nombres([{"quien": "Persona 1"}, {"quien": "Persona 2"}, {"quien": "Yo"}],
                             voces.nombres(tmp_path))
    assert [s["quien"] for s in segs] == ["Ana López", "Persona 2", "Yo"]


def test_con_nombres_la_transcripcion_y_lo_que_va_al_resumen_los_llevan(tmp_path):
    (tmp_path / "transcripcion.json").write_text(json.dumps(
        [{"ini": 1, "fin": 2, "texto": "Hola", "quien": "Persona 1"}]))
    (tmp_path / "resumen.json").write_text("{}")
    voces.poner_nombres(tmp_path, {"Persona 1": "Ana"})

    procesar.procesar(tmp_path, resumen=False, separar=False)

    assert "**Ana:** Hola" in (tmp_path / "transcripcion.md").read_text()
    # El original no se reescribe con el nombre: renombrar es reversible.
    assert json.loads((tmp_path / "transcripcion.json").read_text())[0]["quien"] == "Persona 1"


def test_sin_poder_separar_se_procesa_igual_y_se_dice_por_que(tmp_path, monkeypatch):
    (tmp_path / "transcripcion.json").write_text(json.dumps(
        [{"ini": 1, "fin": 2, "texto": "Hola", "quien": "Reunión"}]))

    def sin_token(c):
        raise voces.SinSeparar("hace falta `hf auth login`")
    monkeypatch.setattr(voces, "separar", sin_token)

    estado = procesar.procesar(tmp_path, resumen=False)

    assert estado["estado"] == "hecho"
    assert estado["etapas"]["voces"].startswith("sin separar: hace falta")
    assert "**Reunión:** Hola" in (tmp_path / "transcripcion.md").read_text()


def test_la_telemetria_de_pyannote_queda_apagada_aunque_el_entorno_la_encienda():
    """🔴 Regla 1: nada sale de la máquina. pyannote la trae encendida."""
    codigo = ("import os; os.environ['PYANNOTE_METRICS_ENABLED']='true';"
              "from reuniones import voces\n"
              "try: voces._tuberia()\n"
              "except Exception: pass\n"
              "from pyannote.audio.telemetry.metrics import is_metrics_enabled\n"
              "print(is_metrics_enabled())")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=300,
                       env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_TOKEN": ""})
    assert r.stdout.strip().splitlines()[-1] == "False", r.stderr[-500:]


REAL = Path("/mnt/d/reuniones/grabaciones/20261021-192505")


@pytest.mark.skipif(not (REAL / "reunion.wav").exists() and not (REAL / "reunion.opus").exists(),
                    reason="hace falta la grabación real")
def test_separa_las_voces_de_una_reunion_real(tmp_path):
    from reuniones.comprimir import audio
    try:
        voces._tuberia()
    except voces.SinSeparar as e:
        pytest.skip(f"modelo sin descargar: {e}")
    t = voces.turnos(audio(REAL, "reunion"))
    assert len({x["voz"] for x in t}) >= 2
    assert all(x["fin"] > x["ini"] for x in t)
