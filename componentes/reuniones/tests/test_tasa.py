"""La frecuencia mal declarada de la pista de la reunión (2-nov: 96 kHz etiquetados como 48)."""
import math
import struct
import wave

from reuniones import carpeta, tasa


def _pista(c, tasa_real, declarada, segundos=2.0):
    """Un tono de 440 Hz grabado a `tasa_real` y etiquetado como `declarada`."""
    n = int(tasa_real * segundos)
    datos = b"".join(struct.pack("<hh", v, v) for v in
                     (int(8000 * math.sin(2 * math.pi * 440 * i / tasa_real)) for i in range(n)))
    with wave.open(str(c / "reunion.wav"), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(declarada)
        w.writeframes(datos)
    carpeta.escribir(c / "meta.json", {"id": "x", "inicio": 1000.0, "fin": 1000.0 + segundos})


def test_una_pista_a_96k_etiquetada_a_48k_se_corrige_y_guarda_la_cabecera_original(tmp_path):
    _pista(tmp_path, 96000, 48000)
    original = (tmp_path / "reunion.wav").read_bytes()[:44]
    hecho = tasa.corregir(tmp_path)
    assert hecho == {"pista": "reunion", "corregida": True, "de": 48000, "a": 96000}
    with wave.open(str(tmp_path / "reunion.wav")) as w:
        assert w.getframerate() == 96000 and abs(w.getnframes() / 96000 - 2.0) < 0.01
    assert (tmp_path / "reunion.wav.cabecera-original").read_bytes() == original
    assert carpeta.leer(tmp_path / "meta.json")["tasa_corregida"]["a"] == 96000


def test_una_pista_bien_declarada_no_se_toca(tmp_path):
    _pista(tmp_path, 48000, 48000)
    antes = (tmp_path / "reunion.wav").read_bytes()
    assert tasa.corregir(tmp_path) is None
    assert (tmp_path / "reunion.wav").read_bytes() == antes


def test_sin_fin_en_meta_no_se_adivina(tmp_path):
    _pista(tmp_path, 96000, 48000)
    carpeta.escribir(tmp_path / "meta.json", {"id": "x", "inicio": 1000.0})
    assert tasa.corregir(tmp_path) is None
