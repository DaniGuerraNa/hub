import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from reuniones import carpeta, procesar, transcribir

MUESTRAS = Path.home() / "projects/voice-assistant/tests/voice-layer/fixtures/audio"


def test_el_eco_del_micro_se_quita_pero_lo_que_dices_tu_se_queda():
    reunion = [{"ini": 1.0, "fin": 4.0, "texto": "Hay que revisar el despliegue de mañana."}]
    micro = [{"ini": 1.3, "fin": 4.2, "texto": "hay que revisar el despliegue de mañana"},
             {"ini": 6.0, "fin": 8.0, "texto": "Yo me encargo."}]
    f = transcribir.fusionar(reunion, micro)
    assert [(s["quien"], s["texto"]) for s in f] == [("Reunión", "Hay que revisar el despliegue de mañana."),
                                                     ("Yo", "Yo me encargo.")]


def test_las_capturas_se_intercalan_por_su_segundo_antes_de_lo_que_se_dice_a_la_vez():
    md = procesar.markdown([{"ini": 4.0, "quien": "Yo", "texto": "mira esto"}],
                           [{"t": 4, "archivo": "000004.jpg"}, {"t": 0, "archivo": "000000.jpg"}], {"id": "x"})
    lineas = [l for l in md.splitlines() if l.startswith(("📷", "["))]
    assert lineas == ["📷 [00:00:00] cambió la pantalla (000000.jpg)",
                      "📷 [00:00:04] cambió la pantalla (000004.jpg)",
                      "[00:00:04] **Yo:** mira esto"]


def test_un_id_que_no_es_fecha_no_llega_a_ser_ruta():
    for malo in ("../etc", "20261020-0900", "x/20261020-090000"):
        with pytest.raises(ValueError):
            carpeta.de(malo)


@pytest.mark.skipif(not MUESTRAS.exists() or not shutil.which("ffmpeg"), reason="hacen falta las muestras y ffmpeg")
def test_transcribe_las_dos_pistas_de_verdad_y_sabe_quien_hablo(tmp_path):
    """Con faster-whisper real (GPU si hay): «la reunión» dice dos frases y
    «yo» una en medio. Lento la primera vez (carga el modelo)."""
    c = tmp_path / "20261020-090000"
    c.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUESTRAS / "sample_reminder.wav", "-i",
                    MUESTRAS / "sample_cancel.wav", "-filter_complex",
                    "[0]apad=pad_dur=4[a];[a][1]concat=n=2:v=0:a=1,aresample=48000", "-ac", "2",
                    c / "reunion.wav"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "3", "-i", "anullsrc=r=16000:cl=mono",
                    "-i", MUESTRAS / "sample_add_note.wav", "-filter_complex",
                    "[0][1]concat=n=2:v=0:a=1,aresample=16000", "-ac", "1", c / "micro.wav"], check=True)
    procesar.procesar(c, resumen=False)
    segs = json.loads((c / "transcripcion.json").read_text())
    assert [s["quien"] for s in segs] == ["Reunión", "Yo", "Reunión"]
    assert "weather observer" in segs[1]["texto"].lower()
    assert json.loads((c / "procesado.json").read_text())["estado"] == "hecho"


@pytest.mark.skipif(not MUESTRAS.exists() or not shutil.which("ffmpeg"), reason="hacen falta las muestras y ffmpeg")
def test_comprimir_deja_opus_que_dura_lo_mismo_borra_el_wav_y_se_sigue_transcribiendo(tmp_path):
    from reuniones import comprimir
    c = tmp_path / "20261020-100000"
    c.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUESTRAS / "sample_reminder.wav", "-ar", "48000",
                    "-ac", "2", c / "reunion.wav"], check=True)
    (c / "meta.json").write_text(json.dumps({"id": c.name, "inicio": 0, "fin": 8}))
    dur = comprimir.duracion(c / "reunion.wav")
    r = comprimir.comprimir(c)
    assert not (c / "reunion.wav").exists() and (c / "reunion.opus").exists()
    assert abs(comprimir.duracion(c / "reunion.opus") - dur) < 0.5
    assert r["despues"] < r["antes"] / 10
    assert comprimir.comprimida(c)
    procesar.procesar(c, resumen=False)
    assert "infraestructura" in (c / "transcripcion.md").read_text()


def test_no_se_comprime_lo_que_se_esta_grabando(tmp_path):
    from reuniones import comprimir
    c = tmp_path / "20261020-100000"
    c.mkdir()
    (c / "meta.json").write_text(json.dumps({"id": c.name, "inicio": 0}))
    (c / "reunion.wav").write_bytes(b"RIFF" + b"\0" * 10000)
    with pytest.raises(RuntimeError, match="grabando"):
        comprimir.comprimir(c)
    assert (c / "reunion.wav").exists()


def test_no_se_comprime_mientras_se_procesa(tmp_path):
    from reuniones import comprimir
    c = tmp_path / "20261020-100000"
    c.mkdir()
    (c / "meta.json").write_text(json.dumps({"id": c.name, "inicio": 0, "fin": 9}))
    (c / "procesado.json").write_text(json.dumps({"estado": "procesando"}))
    (c / "reunion.wav").write_bytes(b"RIFF" + b"\0" * 10000)
    with pytest.raises(RuntimeError, match="procesando"):
        comprimir.comprimir(c)
    assert (c / "reunion.wav").exists()
