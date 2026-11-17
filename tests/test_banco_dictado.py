"""El banco de dictado: frases leídas, guardadas en casa, y el WER de cada Whisper (C-0312).

Lo que se prueba es lo que hace que la cifra se pueda defender (regla dura
13): que la referencia guardada es la frase que se leyó, que el WER cuenta lo
que dice que cuenta con pares conocidos, y que `medir` va de verdad por el
servidor de Whisper —el guion real con un `faster_whisper` de mentira, sin
modelo ni GPU— y lo apaga al terminar. Las frases de estos tests son
inventadas: la lista de quien lo usa no entra nunca en el repo.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time

import pytest

from hub import banco_dictado as banco
from hub import config, transcribir


def _lista(*textos, categoria="corta"):
    return {"version": 3, "frases": [{"id": f"x{i:02d}", "categoria": categoria, "texto": t, "terminos": []}
                                     for i, t in enumerate(textos, 1)]}


@pytest.fixture
def sembrado():
    banco.sembrar({"version": 1, "frases": [
        {"id": "a01", "categoria": "corta", "texto": "Abre la ventana.", "terminos": []},
        {"id": "a02", "categoria": "tecnica", "texto": "Corre los tests con pytest.", "terminos": ["pytest"]},
        {"id": "a03", "categoria": "larga", "texto": "Mañana revisamos el informe del martes.", "terminos": []},
    ]})
    return banco.carpeta()


# ── normalizar y contar errores ──────────────────────────────────────────────

def test_normalizar_quita_puntuacion_y_mayusculas_y_con_tildes_las_conserva():
    assert banco.normalizar("¿Qué tal, Mundo?  ¡Bien!") == "qué tal mundo bien"
    assert banco.normalizar("¿Qué tal, Mundo?", tildes=False) == "que tal mundo"
    assert banco.normalizar("large-v3-turbo") == "large v3 turbo"


@pytest.mark.parametrize("referencia,hipotesis,esperado", [
    ("abre la ventana", "abre la ventana", {"wer": 0.0, "s": 0, "b": 0, "i": 0, "n": 3}),
    ("abre la ventana", "abre la puerta", {"wer": 0.3333, "s": 1, "b": 0, "i": 0, "n": 3}),
    ("abre la ventana", "abre ventana", {"wer": 0.3333, "s": 0, "b": 1, "i": 0, "n": 3}),
    ("abre la ventana", "abre la ventana ya", {"wer": 0.3333, "s": 0, "b": 0, "i": 1, "n": 3}),
    ("abre la ventana", "", {"wer": 1.0, "s": 0, "b": 3, "i": 0, "n": 3}),
    ("Abre la ventana.", "abre, la VENTANA", {"wer": 0.0, "s": 0, "b": 0, "i": 0, "n": 3}),
])
def test_el_wer_cuenta_sustituciones_borrados_e_inserciones(referencia, hipotesis, esperado):
    assert banco.wer(referencia, hipotesis) == esperado


def test_el_wer_sin_tildes_no_cuenta_una_tilde_perdida():
    assert banco.wer("mañana revisó", "manana reviso")["wer"] == 1.0
    assert banco.wer("mañana revisó", "manana reviso", tildes=False)["wer"] == 0.0


def test_el_cer_cuenta_letras():
    assert banco.cer("hola", "hola") == {"cer": 0.0, "s": 0, "b": 0, "i": 0, "n": 4}
    assert banco.cer("hola", "ola")["cer"] == 0.25


# ── la lista: plantilla genérica, rellena y congelada ────────────────────────

def test_sin_lista_sembrada_la_plantilla_se_rellena_con_el_registro_y_el_secretario(tmp_path, monkeypatch):
    asiento = tmp_path / "huerto"
    asiento.mkdir()
    registro = tmp_path / "projects.yml"
    registro.write_text(f"proyectos:\n  - id: huerto\n    nombre: Huerto urbano\n    asiento: {asiento}\n")
    monkeypatch.setattr(config, "projects_yml", lambda: registro)
    frases = banco.frases()
    textos = " ".join(f["texto"] for f in frases)
    assert "{" not in textos and "}" not in textos
    assert "Huerto urbano" in textos and "Secretario" in textos
    assert len(frases) == len(banco.PLANTILLA) >= 30
    assert len({f["id"] for f in frases}) == len(frases)
    assert {f["categoria"] for f in frases} >= {"corta", "tecnica", "cifras", "larga"}
    assert not (banco.carpeta() / "frases.yml").exists()   # leerla no escribe nada


def test_sembrar_deja_la_lista_en_casa_solo_para_el_dueno():
    assert banco.sembrar(_lista("Uno dos tres.", "Cuatro cinco.")) == 2
    ruta = banco.carpeta() / "frases.yml"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert stat.S_IMODE(banco.carpeta().stat().st_mode) == 0o700
    assert [f["texto"] for f in banco.frases()] == ["Uno dos tres.", "Cuatro cinco."]


def test_sembrar_se_niega_si_ya_hay_grabaciones(sembrado):
    banco.guardar("pc", "a01", b"audio", "a.webm", {})
    with pytest.raises(ValueError, match="ya hay 1 grabaci"):
        banco.sembrar(_lista("Otra cosa."))


@pytest.mark.parametrize("mala", [
    {"frases": [{"id": "../x", "categoria": "corta", "texto": "hola"}]},
    {"frases": [{"id": "a1", "categoria": "corta", "texto": ""}]},
    {"frases": [{"id": "a1", "categoria": "corta", "texto": "uno\ndos"}]},
    {"frases": [{"id": "a1", "categoria": "corta", "texto": "uno"}, {"id": "a1", "categoria": "corta", "texto": "dos"}]},
    {"frases": []},
])
def test_sembrar_rechaza_una_lista_mal_hecha(mala):
    with pytest.raises(ValueError):
        banco.sembrar(mala)


def test_la_primera_grabacion_congela_la_lista():
    """Cambiar el registro después no puede cambiar lo que se leyó."""
    primera = banco.frases()[0]
    banco.guardar("pc", primera["id"], b"audio", "a.webm", {})
    assert (banco.carpeta() / "frases.yml").exists()
    assert banco.frases()[0] == primera


# ── guardar ──────────────────────────────────────────────────────────────────

def test_guardar_deja_el_audio_y_su_referencia_en_casa(sembrado):
    progreso = banco.guardar("telefono", "a02", b"OggS-voz", "toma.ogg",
                             {"echoCancellation": True, "sampleRate": 48000, "deviceId": "abc", "raro": {"x": 1}},
                             esperado="Corre los tests con pytest.")
    assert progreso == {"aparato": "telefono", "hechas": 1, "total": 3, "siguiente": "a01"}
    audio = sembrado / "telefono-a02.ogg"
    assert audio.read_bytes() == b"OggS-voz" and stat.S_IMODE(audio.stat().st_mode) == 0o600
    (linea,) = (sembrado / "grabaciones.jsonl").read_text().splitlines()
    g = json.loads(linea)
    assert g["referencia"] == "Corre los tests con pytest." and g["categoria"] == "tecnica"
    assert g["terminos"] == ["pytest"] and g["archivo"] == "telefono-a02.ogg" and g["bytes"] == 8
    # Del micrófono, lo que dice cómo sonó; no su identificador ni lo que no se espera.
    assert g["micro"] == {"echoCancellation": True, "sampleRate": 48000}
    assert stat.S_IMODE((sembrado / "grabaciones.jsonl").stat().st_mode) == 0o600


def test_repetir_una_frase_la_sustituye_y_no_la_cuenta_dos_veces(sembrado):
    banco.guardar("pc", "a01", b"primera", "a.webm", {})
    progreso = banco.guardar("pc", "a01", b"segunda", "a.ogg", {})
    assert progreso["hechas"] == 1
    assert not (sembrado / "pc-a01.webm").exists()
    assert (sembrado / "pc-a01.ogg").read_bytes() == b"segunda"
    assert len((sembrado / "grabaciones.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("aparato,frase,datos,esperado,motivo", [
    ("tablet", "a01", b"x", None, "aparato"),
    ("pc", "zz9", b"x", None, "no está en la lista"),
    ("pc", "a01", b"", None, "vacío"),
    ("pc", "a01", b"x", "Otra frase que no es.", "cambió"),
])
def test_guardar_rechaza_lo_que_no_cuadra(sembrado, aparato, frase, datos, esperado, motivo):
    with pytest.raises(ValueError, match=motivo):
        banco.guardar(aparato, frase, datos, "a.webm", {}, esperado=esperado)
    assert not list(sembrado.glob("*.webm"))


def test_borrar_y_vaciar(sembrado):
    for aparato in banco.APARATOS:
        for frase in ("a01", "a02"):
            banco.guardar(aparato, frase, b"x", "a.webm", {})
    assert banco.borrar("pc", "a01") is True
    assert banco.borrar("pc", "a01") is False
    assert banco.progreso("pc")["hechas"] == 1 and not (sembrado / "pc-a01.webm").exists()
    assert banco.vaciar("telefono") == 2
    assert banco.progreso("telefono")["hechas"] == 0 and banco.progreso("pc")["hechas"] == 1
    assert banco.vaciar() == 1
    assert (sembrado / "frases.yml").exists()   # la lista se queda


def test_la_poda_de_dictados_no_toca_el_banco(sembrado):
    """Lo guardado a propósito no caduca (matiza la 362): `podar_dictados`
    borra los audios sueltos de `voz/` y no entra en `voz/banco/`."""
    banco.guardar("pc", "a01", b"x", "a.webm", {})
    hace_un_mes = time.time() - 30 * 86400
    os.utime(sembrado / "pc-a01.webm", (hace_un_mes, hace_un_mes))
    suelto = sembrado.parent / "261001-101010-1.webm"
    suelto.write_bytes(b"x")
    os.utime(suelto, (hace_un_mes, hace_un_mes))
    assert transcribir.podar_dictados() == 1
    assert (sembrado / "pc-a01.webm").exists() and not suelto.exists()


# ── medir: por el servidor de verdad, con un Whisper de mentira ──────────────

GUION_SERVIDOR = config.RAIZ_REPO / "scripts" / "transcribir-servidor.py"


@pytest.fixture
def whisper_falso(tmp_path, monkeypatch):
    """El guion del servidor de verdad, lanzado por `transcribir.arrancar_servidor`
    con un `faster_whisper` que «oye» el contenido del archivo: lo que se
    prueba es el camino entero, no Whisper. Sin systemd: la suite no monta
    scopes. HUB_HOME corto, que la ruta del socket tiene tope."""
    from hub import procesos
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "import os\n"
        "class _T:\n    def __init__(s, t): s.text = t\n"
        "class _I:\n    duration = 2.0\n    duration_after_vad = 1.5\n"
        "class WhisperModel:\n"
        "    def __init__(s, nombre, device='cpu', compute_type='', **k): s.nombre = nombre\n"
        "    def transcribe(s, ruta, **k):\n"
        "        if not isinstance(ruta, str): return iter(()), None\n"
        "        texto = open(ruta).read()\n"
        "        if s.nombre == 'torpe': texto = texto.replace('ventana', 'mentana')\n"
        "        return [_T(texto)], _I()\n")
    casa = tmp_path / "h"
    casa.mkdir()
    monkeypatch.setattr(config, "HUB_HOME", casa)
    monkeypatch.setenv("PYTHONPATH", str(falso))
    monkeypatch.setattr(procesos, "_puede", False)
    monkeypatch.setattr(transcribir, "interprete_del_servidor", lambda: sys.executable)
    return casa


def _grabar(textos: dict[str, str]):
    for (aparato, frase), dicho in textos.items():
        banco.guardar(aparato, frase, dicho.encode(), "a.webm", {})


def test_medir_va_por_el_servidor_calcula_el_wer_y_lo_apaga(whisper_falso, sembrado):
    _grabar({("pc", "a01"): "Abre la ventana.", ("pc", "a02"): "Corre los tests con pi test.",
             ("telefono", "a01"): "abre la ventana"})
    avances = []
    r = banco.medir([{"modelo": "small", "tipo": "int8", "dispositivo": "cpu"}, {"modelo": "torpe"}],
                    al_avance=avances.append)
    bien, torpe = r["configs"]
    assert bien["servidor"]["modelo"] == "small" and bien["servidor"]["tipo"] == "int8"
    assert bien["servidor"]["dispositivo"] == "cpu"
    # 11 palabras de referencia; «pytest» → «pi test»: una sustitución y una inserción.
    assert bien["totales"]["wer"] == pytest.approx(2 / 11, abs=1e-4)
    assert bien["totales"]["terminos"] == 0.0     # el único término, «pytest», no se oyó
    assert bien["por_aparato"]["telefono"]["wer"] == 0.0
    assert bien["por_categoria"]["corta"]["wer"] == 0.0
    assert torpe["totales"]["wer"] > bien["totales"]["wer"]
    assert {f["frase"] for f in bien["frases"]} == {"a01", "a02"}
    assert bien["frases"][0]["ms_whisper"] is not None
    # Lo dejó escrito, sólo para el dueño, y no quedó ningún servidor.
    (archivo,) = (banco.carpeta() / "resultados").glob("*.json")
    assert stat.S_IMODE(archivo.stat().st_mode) == 0o600
    assert json.loads(archivo.read_text())["configs"][1]["config"]["modelo"] == "torpe"
    assert not (banco.carpeta() / "medir.sock").exists()
    assert any(a.get("fase") == "frase" for a in avances)
    assert banco.resultados()[0]["configs"][0]["totales"]["wer"] == bien["totales"]["wer"]


def test_medir_apaga_antes_el_whisper_del_dictado(whisper_falso, sembrado):
    """Un modelo a la vez: el del dictado ocupa la misma GPU."""
    import subprocess
    _grabar({("pc", "a01"): "Abre la ventana."})
    voz = config.HUB_HOME / "voz"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(voz / "whisper.sock"), "--ocioso", "30"],
                         env=dict(os.environ))
    try:
        for _ in range(200):
            if (voz / "whisper.sock").exists():
                break
            time.sleep(0.05)
        assert (voz / "whisper.sock").exists()
        banco.medir([{"modelo": "small"}])
        assert p.wait(5) == 0 and not (voz / "whisper.sock").exists()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_medir_no_empieza_si_reuniones_esta_procesando(whisper_falso, sembrado, monkeypatch):
    from hub import reuniones
    _grabar({("pc", "a01"): "Abre la ventana."})
    monkeypatch.setattr(reuniones, "procesando", lambda: ["20261112-090000"])
    monkeypatch.setattr(transcribir, "arrancar_servidor", lambda *a, **k: pytest.fail("cargó otro modelo"))
    with pytest.raises(banco.Ocupado, match="20261112-090000"):
        banco.medir([{"modelo": "small"}])


def test_medir_con_el_banco_vacio_lo_dice(whisper_falso, sembrado):
    with pytest.raises(ValueError, match="vacío"):
        banco.medir([{"modelo": "small"}])


def test_un_procesado_de_reuniones_vivo_cuenta_y_uno_cortado_no(tmp_path, monkeypatch):
    from hub import procesos, reuniones
    raiz = tmp_path / "grabaciones"
    monkeypatch.setenv("REUNIONES_RAIZ", str(raiz))
    for nombre in ("20261112-090000", "20261112-100000", "20261112-110000"):
        (raiz / nombre).mkdir(parents=True)
    (raiz / "20261112-090000" / "procesado.json").write_text(json.dumps({"estado": "procesando",
                                                                         "inicio": time.time()}))
    (raiz / "20261112-100000" / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    (raiz / "20261112-110000" / "procesado.json").write_text(json.dumps({"estado": "procesando",
                                                                         "inicio": time.time()}))
    lanzados = reuniones.carpeta() / "lanzados"
    lanzados.mkdir(parents=True, exist_ok=True)
    (lanzados / "20261112-090000-procesar.json").write_text(
        json.dumps({**procesos.huella(os.getpid()), "desde": time.time()}))
    (lanzados / "20261112-110000-procesar.json").write_text(
        json.dumps({"pid": 999999, "arranque": "0", "desde": time.time()}))
    assert reuniones.procesando() == ["20261112-090000"]


# ── la línea de comandos ─────────────────────────────────────────────────────

def test_la_linea_de_comandos_siembra_dice_el_estado_y_lista_las_frases(tmp_path, capsys):
    archivo = tmp_path / "mis-frases.yml"
    archivo.write_text("version: 2\nfrases:\n  - {id: z01, categoria: corta, texto: \"Hola, mundo.\", terminos: []}\n")
    assert banco.main(["sembrar", "--de", str(archivo)]) == 0
    assert banco.main(["frases"]) == 0
    assert "Hola, mundo." in capsys.readouterr().out
    banco.guardar("pc", "z01", b"x", "a.webm", {})
    assert banco.main(["estado"]) == 0
    salida = capsys.readouterr().out
    assert "PC: 1 de 1" in salida and "Teléfono: 0 de 1" in salida
    assert banco.main(["sembrar", "--de", str(archivo)]) == 1


def test_la_linea_de_comandos_mide_y_ensena_la_tabla(whisper_falso, sembrado, capsys):
    _grabar({("pc", "a01"): "Abre la ventana."})
    assert banco.main(["medir", "--modelos", "small,torpe", "--dispositivo", "cpu"]) == 0
    salida = capsys.readouterr().out
    assert "small" in salida and "torpe" in salida and "WER" in salida
    assert banco.main(["resultados"]) == 0
    assert "torpe" in capsys.readouterr().out


# ── la pantalla y sus rutas ──────────────────────────────────────────────────

@pytest.fixture
def cliente():
    from fastapi.testclient import TestClient

    from hub import web
    return TestClient(web.app, base_url="http://127.0.0.1:8787")


CASA = {"Origin": "http://127.0.0.1:8787"}


def test_la_pantalla_ensena_la_frase_y_el_progreso(cliente, sembrado):
    banco.guardar("pc", "a01", b"x", "a.webm", {})
    html = cliente.get("/voz/banco?aparato=pc").text
    assert "Corre los tests con pytest." in html          # la siguiente sin grabar
    assert "/static/banco-dictado.js" in html and 'id="banco-datos"' in html
    datos = json.loads(html.split('id="banco-datos">', 1)[1].split("</script>", 1)[0])
    assert datos["aparato"] == "pc"
    assert [a["hechas"] for a in datos["aparatos"]] == [1, 0]
    assert datos["frases"][0] == {"id": "a01", "categoria": "corta", "texto": "Abre la ventana.",
                                  "grabada": {"pc": True, "telefono": False}}


def test_la_api_de_lectura_dice_lo_mismo_que_la_pantalla(sembrado):
    from hub import api
    b = api.banco_dictado("telefono")
    assert b["aparato"] == "telefono" and b["total"] == 3
    assert api.banco_dictado("tablet")["aparato"] == "pc"


def test_subir_una_toma_la_guarda_y_devuelve_el_progreso(cliente, sembrado):
    r = cliente.post("/api/voz/banco", headers=CASA, files={"audio": ("a.webm", b"voz")},
                     data={"frase": "a02", "aparato": "pc", "texto": "Corre los tests con pytest.",
                           "micro": json.dumps({"noiseSuppression": False})})
    assert r.json() == {"ok": True, "progreso": {"aparato": "pc", "hechas": 1, "total": 3, "siguiente": "a01"}}
    assert (sembrado / "pc-a02.webm").read_bytes() == b"voz"
    malo = cliente.post("/api/voz/banco", headers=CASA, files={"audio": ("a.webm", b"voz")},
                        data={"frase": "a02", "aparato": "tablet"}).json()
    assert malo["ok"] is False and "aparato" in malo["error"]
    ajeno = cliente.post("/api/voz/banco", headers={"Origin": "https://malo.example"},
                         files={"audio": ("a.webm", b"voz")}, data={"frase": "a01", "aparato": "pc"})
    assert ajeno.status_code == 403 and not (sembrado / "pc-a01.webm").exists()


def test_borrar_y_vaciar_desde_la_pantalla_vuelven_a_ella(cliente, sembrado):
    banco.guardar("pc", "a01", b"x", "a.webm", {})
    banco.guardar("pc", "a02", b"x", "a.webm", {})
    r = cliente.post("/voz/banco/borrar", headers=CASA, data={"frase": "a01", "aparato": "pc"},
                     follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/voz/banco?aparato=pc")
    assert banco.progreso("pc")["hechas"] == 1
    r = cliente.post("/voz/banco/vaciar", headers=CASA, data={"aparato": "pc"}, follow_redirects=False)
    assert r.status_code == 303 and banco.progreso("pc")["hechas"] == 0
    r = cliente.post("/voz/banco/borrar", headers=CASA, data={"frase": "a01", "aparato": "../x"},
                     follow_redirects=False)
    assert r.headers["location"].startswith("/voz/banco?aviso=")


# ── lo que marcó el revisor ──────────────────────────────────────────────────

def test_dos_medidas_a_la_vez_no_se_mezclan(whisper_falso, sembrado):
    """Las dos compartirían `medir.sock`: una se niega, como con Reuniones."""
    import fcntl
    _grabar({("pc", "a01"): "Abre la ventana."})
    with open(banco.carpeta() / "medir.lock", "w") as otra:
        fcntl.flock(otra, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(banco.Ocupado, match="otra medida"):
            banco.medir([{"modelo": "small"}])
    assert banco.medir([{"modelo": "small"}])["configs"][0]["totales"]["wer"] == 0.0


def test_cada_configuracion_dice_si_el_whisper_del_dictado_estaba_cargado_al_acabar(whisper_falso, sembrado):
    """Si alguien dictó mientras se medía, hubo dos modelos a la vez: la cifra
    puede no ser la suya, y se apunta."""
    _grabar({("pc", "a01"): "Abre la ventana."})
    dictado = config.HUB_HOME / "voz" / "whisper.sock"

    def alguien_dicta(a):
        if a["fase"] == "frase" and a["config"]["modelo"] == "torpe":
            dictado.write_text("")
    r = banco.medir([{"modelo": "small"}, {"modelo": "torpe"}], al_avance=alguien_dicta)
    assert [c["dictado_cargado"] for c in r["configs"]] == [False, True]


def test_medir_guarda_cada_configuracion_al_acabarla(whisper_falso, sembrado):
    """Un Ctrl+C en la segunda no puede perder la primera."""
    _grabar({("pc", "a01"): "Abre la ventana."})

    def cortar(a):
        if a["fase"] == "cargando" and a["config"]["modelo"] == "torpe":
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        banco.medir([{"modelo": "small"}, {"modelo": "torpe"}], al_avance=cortar)
    (archivo,) = (banco.carpeta() / "resultados").glob("*.json")
    guardado = json.loads(archivo.read_text())
    assert [c["config"]["modelo"] for c in guardado["configs"]] == ["small"]
    assert guardado["terminada"] is False
    assert banco.resultados()[0]["terminada"] is False
    assert stat.S_IMODE((banco.carpeta() / "servidor.log").stat().st_mode) == 0o600


def _fila(categoria, referencia, respuesta):
    return banco._puntuar({"frase": "x", "aparato": "pc", "categoria": categoria, "referencia": referencia,
                           "terminos": []}, respuesta)


def test_las_cifras_van_aparte_y_una_frase_sin_respuesta_no_cuenta_como_error_total():
    filas = [_fila("corta", "abre la ventana", {"texto": "abre la ventana"}),
             _fila("corta", "cierra la puerta", None),                      # el servidor no contestó
             _fila("cifras", "son tres mil", {"texto": "son 3000"})]
    informe = banco._informe(filas)
    assert informe["totales"]["wer"] == 0.0            # ni la sin respuesta ni las cifras
    assert informe["totales"]["errores"] == 1 and informe["totales"]["frases"] == 1
    assert informe["por_categoria"]["cifras"]["wer"] == pytest.approx(2 / 3, abs=1e-4)
    assert informe["por_categoria"]["corta"]["errores"] == 1


def test_el_percentil_es_el_de_rango_mas_cercano():
    assert banco._percentil([1, 2], 0.5) == 1
    assert banco._percentil([1, 2, 3, 4], 0.5) == 2
    assert banco._percentil(list(range(1, 11)), 0.9) == 9
    assert banco._percentil([], 0.5) is None


def test_un_jsonl_tocado_a_mano_no_hace_borrar_fuera_del_banco(sembrado):
    testigo = config.HUB_HOME / "testigo.txt"
    testigo.write_text("no me borres")
    banco.guardar("pc", "a01", b"x", "a.webm", {})
    with open(sembrado / "grabaciones.jsonl", "a") as f:
        for archivo in ("../../testigo.txt", "../banco/../../testigo.txt", str(testigo)):
            f.write(json.dumps({"frase": "a02", "aparato": "pc", "archivo": archivo}) + "\n")
    assert banco.borrar("pc", "a02") is True
    assert banco.vaciar("pc") == 1
    assert testigo.read_text() == "no me borres"


def test_un_id_raro_en_la_lista_editada_a_mano_no_se_guarda(sembrado):
    (sembrado / "frases.yml").write_text("version: 1\nfrases:\n"
                                         "  - {id: '../../fuera', categoria: corta, texto: Hola., terminos: []}\n")
    with pytest.raises(ValueError, match="no vale"):
        banco.guardar("pc", "../../fuera", b"x", "a.webm", {})
    assert not list(config.HUB_HOME.rglob("*fuera*"))


def test_lo_que_dice_el_micro_se_acota():
    assert banco._micro({"sampleRate": float("nan"), "latency": float("inf"), "channelCount": 10 ** 4000,
                         "autoGainControl": -5e9, "sampleSize": 16, "echoCancellation": True,
                         "noiseSuppression": "z" * 41}) == {"sampleSize": 16, "echoCancellation": True}


def test_la_pantalla_dice_las_cifras_aparte_las_sin_respuesta_y_si_quedo_a_medias(cliente, sembrado):
    (sembrado / "resultados").mkdir()
    (sembrado / "resultados" / "20261112-030000.json").write_text(json.dumps({
        "fecha": "20261112-030000", "version": 1, "grabaciones": 3, "terminada": False, "configs": [
            {"config": {"modelo": "small"}, "servidor": {"tipo": "int8", "dispositivo": "cpu", "s_carga": 1.2},
             "dictado_cargado": True,
             "totales": {"wer": 0.1, "wer_sin_tildes": 0.1, "terminos": 0.5, "errores": 2, "ms_p50": 300},
             "por_categoria": {"cifras": {"wer": 0.25}}}]}))
    html = cliente.get("/voz/banco").text
    assert "25,0 %" in html                     # la columna de cifras
    assert "a medias" in html and "Whisper del dictado" in html
    assert ">2<" in html                        # sin respuesta


def test_un_termino_que_se_queda_en_nada_al_normalizar_no_cuenta_como_acertado():
    assert banco._contiene("", "++") is False
    assert banco._contiene("lanza pytest ya", "pytest") is True
