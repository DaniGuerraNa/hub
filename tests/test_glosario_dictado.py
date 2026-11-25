"""El glosario del dictado del dueño (C-0036, decisión 453).

Con turbo, lo que queda de error son nombres propios y términos técnicos
(24-nov: Tailscale→Tilescale, Claude→Cloud, SQLite WAL→«modo Wild»). El
glosario se le da a Whisper en cada frase; lo compone el hub, viaja en el
pedido y el servidor dice qué aplicó. Sólo para el dictado del dueño.

El servidor es el guion de verdad con un `faster_whisper` falso que repite
lo que le llega en `hotwords` o `initial_prompt`: se prueba el camino, no Whisper.
"""

from __future__ import annotations

import sys
import time

import pytest

from hub import procesos, registry, transcribir

FALSO = '''
class _T:
    def __init__(s, t): s.text = t
class WhisperModel:
    def __init__(s, *a, **k): pass
    def transcribe(s, ruta, **k):
        if not isinstance(ruta, str):
            return [], None
        extra = sorted(c for c in ("hotwords", "initial_prompt") if c in k)
        return [_T(open(ruta).read() + (" [" + ",".join(extra) + "]" if extra else ""))], None
'''


@pytest.fixture
def casa(tmp_path, monkeypatch):
    from hub import config

    falso = tmp_path / "falso" / "faster_whisper"
    falso.mkdir(parents=True)
    (falso / "__init__.py").write_text(FALSO)
    monkeypatch.setenv("PYTHONPATH", str(falso.parent))
    monkeypatch.setattr(config, "HUB_HOME", tmp_path / "h")
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: "")
    monkeypatch.setattr(transcribir, "por_omision", lambda: [sys.executable, "guion", "{audio}"])
    monkeypatch.setattr(procesos, "puede_desasir", lambda: False)
    monkeypatch.setattr(registry, "nombres_activos", lambda: ["Proyecto Uno"])
    voz = tmp_path / "h" / "voz"
    yield voz
    try:
        transcribir.apagar_servidor(voz / "whisper.sock", 3)
    except RuntimeError:
        pass


def _con_servidor(voz):
    voz.mkdir(parents=True, exist_ok=True)
    transcribir._arrancar_servidor(voz / "whisper.sock")
    limite = time.monotonic() + 15
    while time.monotonic() < limite and not transcribir._escucha(voz / "whisper.sock"):
        time.sleep(0.05)


def _pedir(voz, glosario=None) -> dict:
    audio = voz / "frase.webm"
    audio.write_text("abre tailscale")
    pedido = {"ruta": str(audio), "idioma": "es"}
    if glosario is not None:
        pedido["glosario"] = glosario
    return transcribir.pedir(voz / "whisper.sock", pedido)


def test_sin_glosario_whisper_recibe_lo_de_siempre(casa):
    _con_servidor(casa)
    r = _pedir(casa)
    assert r["texto"] == "abre tailscale" and r["medidas"]["glosario"] == "no"


@pytest.mark.parametrize("modo, argumento", [("hotwords", "hotwords"), ("prompt", "initial_prompt")])
def test_cada_modo_llega_por_su_argumento_y_nunca_los_dos(casa, modo, argumento):
    _con_servidor(casa)
    r = _pedir(casa, {"modo": modo, "texto": "Tailscale, Claude"})
    assert r["texto"] == f"abre tailscale [{argumento}]"
    assert r["medidas"]["glosario"] == modo and r["medidas"]["glosario_caracteres"] == len("Tailscale, Claude")


@pytest.mark.parametrize("malo", [{"modo": "todo", "texto": "x"}, {"modo": "hotwords", "texto": ""},
                                  {"modo": "hotwords", "texto": "x" * 3000}, "Tailscale", {"modo": "prompt"}])
def test_un_glosario_mal_formado_no_rompe_la_frase_y_dice_que_no_se_aplico(casa, malo):
    _con_servidor(casa)
    r = _pedir(casa, malo)
    assert r["texto"] == "abre tailscale" and r["medidas"]["glosario"] == "no"


def test_sin_archivo_es_la_base_mas_los_proyectos_y_no_escribe_nada(casa):
    g = transcribir.glosario()
    assert g["de"] == {"origen": "base", "proyectos": 1}
    assert g["terminos_lista"][0] == transcribir.GLOSARIO_BASE[0] and g["terminos_lista"][-1] == "Proyecto Uno"
    assert not transcribir.ruta_glosario().exists()


def test_el_archivo_sustituye_a_la_base_y_los_proyectos_entran_siempre(casa):
    casa.mkdir(parents=True)
    transcribir.ruta_glosario().write_text("# mío\nCometa\n\nTailscale\ncometa\n")
    g = transcribir.glosario()
    assert g["terminos_lista"] == ["Cometa", "Tailscale", "Proyecto Uno"]   # sin repetidos, sin comentarios
    assert g["texto"] == "Cometa, Tailscale, Proyecto Uno." and g["de"]["origen"] == "archivo"


def test_lo_que_no_cabe_se_recorta_por_la_cola_y_se_dice(casa, monkeypatch):
    monkeypatch.setattr(registry, "nombres_activos", lambda: ["Último"])
    casa.mkdir(parents=True)
    transcribir.ruta_glosario().write_text("\n".join(f"termino{i:03d}" for i in range(80)))
    g = transcribir.glosario()
    assert g["recortado"] and len(g["texto"]) <= transcribir.TOPE_GLOSARIO
    assert g["terminos_lista"][0] == "termino000" and "Último" not in g["terminos_lista"]


def test_sembrar_escribe_la_base_para_el_dueno_una_sola_vez(casa):
    import stat
    assert transcribir.sembrar_glosario() is True
    assert stat.S_IMODE(transcribir.ruta_glosario().stat().st_mode) == 0o600
    transcribir.ruta_glosario().write_text("Cometa\n")
    assert transcribir.sembrar_glosario() is False and transcribir.glosario()["terminos_lista"][0] == "Cometa"


def test_el_dictado_lo_manda_al_servidor_con_el_modo_fijado(casa, monkeypatch):
    monkeypatch.setattr(transcribir, "GLOSARIO_MODO", "prompt")
    _con_servidor(casa)
    medidas: dict = {}
    assert transcribir.dictado(b"abre tailscale", "f.webm", medidas=medidas) == "abre tailscale [initial_prompt]"
    assert medidas["glosario"] == "prompt" and medidas["camino"] == "servidor"
    linea = transcribir.linea_de_medidas(medidas)
    assert "glosario=prompt" in linea and "Tailscale" not in linea and "Proyecto" not in linea


def test_por_el_camino_frio_la_frase_lleva_el_mismo_glosario(casa, monkeypatch):
    monkeypatch.setattr(transcribir, "GLOSARIO_MODO", "hotwords")
    monkeypatch.setattr(transcribir, "_servidor", lambda *a, **k: None)
    usados = []
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: usados.append(transcribir.comando(aj)) or "x")
    medidas: dict = {}
    transcribir.dictado(b"x", "f.webm", medidas=medidas)
    linea = usados[0]
    assert "--glosario-modo=hotwords" in linea
    assert f"--glosario={transcribir.glosario()['texto']}" in linea
    assert medidas["glosario"] == "hotwords"


def test_el_modo_del_dictado_es_el_que_fijo_la_medida():
    """`prompt`: `hotwords` perdía 42 de 262 palabras en un dictado de 2,5 min."""
    assert transcribir.GLOSARIO_MODO == "prompt"


def test_un_archivo_en_otra_codificacion_no_tumba_el_dictado_y_un_bom_no_se_cuela(casa):
    casa.mkdir(parents=True)
    transcribir.ruta_glosario().write_bytes("Árbol\n".encode("latin-1"))
    assert transcribir.glosario()["de"]["origen"] == "base"
    transcribir.ruta_glosario().write_bytes("\ufeffCometa\n".encode("utf-8"))
    assert transcribir.glosario()["terminos_lista"][0] == "Cometa"


def test_sin_modo_fijado_el_dictado_va_sin_glosario(casa, monkeypatch):
    monkeypatch.setattr(transcribir, "GLOSARIO_MODO", None)
    _con_servidor(casa)
    assert transcribir.dictado(b"abre tailscale", "f.webm") == "abre tailscale"


def test_las_voces_de_otros_se_transcriben_sin_el_glosario_del_dueno(casa, monkeypatch, tmp_path):
    """Encargos, orquestador y Telegram van por `transcribir.transcribir`:
    los términos del dueño sesgarían lo que dice otra persona."""
    monkeypatch.setattr(transcribir, "GLOSARIO_MODO", "hotwords")
    audio = tmp_path / "otro.ogg"
    audio.write_text("x")
    eco = [sys.executable, "-c", "import sys; print(' '.join(sys.argv[1:]))", "{audio}"]
    assert "--glosario" not in transcribir.transcribir(audio, {"transcripcion": {"comando": eco}})
    from hub import orquestador, rele_encargos
    from hub.secretario.fuentes import telegram
    for modulo in (orquestador, rele_encargos, telegram):
        fuente = open(modulo.__file__, encoding="utf-8").read()
        assert "transcribir.dictado(" not in fuente and "glosario(" not in fuente, modulo.__name__
