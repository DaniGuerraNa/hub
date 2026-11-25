"""Pasar un audio a texto con un comando de fuera: qué se exige y cómo se falla.

El hub no trae whisper (decisión 221 y la cabecera del módulo), así que aquí lo
que se prueba de verdad es **el trato con un programa ajeno**: que el que falta
se diga con la línea exacta que hay que escribir, que el mal configurado se
rechace antes de gastar un audio, y que los dos modos de no tener texto queden
separados.

Los transcriptores de estos tests son guiones de Python ejecutados de verdad, no
un `subprocess.run` sustituido: lo que se quiere comprobar es el manejo de un
proceso que sale con código 3 o que no imprime nada, y un doble sólo probaría el
doble.
"""

from __future__ import annotations

import sys

import pytest

from hub import transcribir


def con_comando(comando) -> dict:
    return {"transcripcion": {"comando": comando}}


def guion(codigo: str) -> list[str]:
    """Un transcriptor de mentira, pero un proceso de verdad.

    `{audio}` va como último argumento, que es donde lo pondría cualquiera.
    """
    return [sys.executable, "-c", codigo, "{audio}"]


@pytest.fixture
def audio(tmp_path):
    ruta = tmp_path / "nota-0001.oga"
    ruta.write_bytes(b"OggS-una-nota-de-voz")
    return ruta


# ── lo que falta, dicho de forma que se pueda arreglar ───────────────────────


@pytest.mark.parametrize(
    "ajustes",
    [None, {}, {"transcripcion": {}}, {"transcripcion": {"comando": ""}}],
)
def test_sin_transcriptor_el_error_trae_dentro_la_linea_de_yaml_que_falta(ajustes):
    """🔴 El mensaje de error es la documentación de esta función.

    Quien se encuentra esto no está leyendo el código: está mirando por qué un
    audio se quedó aparcado. «No hay transcriptor» a secas le deja buscando en
    qué archivo y con qué forma; con la línea dentro, lo arregla y reintenta.
    """
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.comando(ajustes)

    mensaje = str(exc.value)
    assert "encargos.yml" in mensaje
    assert "transcripcion:" in mensaje and "comando:" in mensaje
    assert "{audio}" in mensaje


def test_un_comando_que_no_dice_donde_va_el_archivo_se_rechaza_al_configurarlo():
    """Y no al usarlo, que es la diferencia entre un aviso y un audio perdido.

    Sin `{audio}` el transcriptor se ejecutaría sin recibir nada y devolvería
    vacío: eso llega como «no se entendió» y se le acabaría preguntando a la
    persona que repita algo que sí se oía. El comando se valida solo, sin audio
    delante, para que el fallo salga cuando se escribe la configuración.
    """
    with pytest.raises(transcribir.SinTranscriptor, match="dónde va el archivo"):
        transcribir.comando(con_comando("/opt/whisper/transcribe.sh --modelo base"))


# ── cadena o lista ───────────────────────────────────────────────────────────


def test_una_cadena_se_parte_respetando_las_comillas():
    """La cadena es lo que uno escribe la primera vez, así que se admite; pero
    partirla por espacios a secas rompería la primera ruta con un espacio."""
    linea = '"/opt/mis cosas/whisper.sh" --modelo base {audio}'
    assert transcribir.comando(con_comando(linea)) == [
        "/opt/mis cosas/whisper.sh", "--modelo", "base", "{audio}",
    ]


def test_una_lista_se_respeta_tal_cual():
    """La lista es la forma correcta: nada que interpretar, nada que partir por
    donde no es."""
    partes = ["/opt/mis cosas/whisper.sh", "--modelo", "base", "{audio}"]
    assert transcribir.comando(con_comando(partes)) == partes


# ── ejecutar ─────────────────────────────────────────────────────────────────


def test_el_audio_se_le_pasa_donde_el_comando_dice_audio(audio):
    """La sustitución es todo el contrato con el programa de fuera: si el
    marcador se quedara sin reemplazar, el transcriptor abriría un archivo
    llamado literalmente «{audio}»."""
    ajustes = con_comando(guion("import sys; print(sys.argv[1])"))
    assert transcribir.transcribir(audio, ajustes) == str(audio)


def test_el_texto_vuelve_sin_los_espacios_de_los_bordes(audio):
    """Los transcriptores sueltan saltos de línea al final. Ese blanco viajaría
    hasta la ficha del encargo y de ahí al prompt del agente."""
    ajustes = con_comando(guion('print("\\n  abro a las siete y apunto los fiados\\n")'))
    assert transcribir.transcribir(audio, ajustes) == "abro a las siete y apunto los fiados"


def test_un_audio_que_no_esta_no_llega_a_ejecutar_nada(tmp_path, monkeypatch):
    """Lanzar el proceso para que falle dentro cuesta segundos y devuelve un
    error del transcriptor sobre un archivo que nunca existió."""
    monkeypatch.setattr(
        transcribir.subprocess, "run",
        lambda *a, **k: pytest.fail("no había audio y aun así se ejecutó el transcriptor"),
    )
    with pytest.raises(transcribir.SinTranscriptor, match="no existe el audio"):
        transcribir.transcribir(tmp_path / "no-esta.oga", con_comando(guion("pass")))


# ── los tres modos de no obtener texto, y por qué no son el mismo ────────────


def test_no_haber_podido_y_no_haber_entendido_son_errores_distintos():
    """🔴 El test que fija la distinción entera.

    «No se pudo transcribir» se arregla —falta un modelo, falta ffmpeg— y se
    reintenta con el mismo audio. «Se transcribió y no dijo nada» no se arregla
    tocando la máquina: hay que preguntarle a la persona. Si una heredara de la
    otra, un `except` escrito de buena fe las juntaría y el audio mudo entraría
    en la cola de reintentos para siempre.
    """
    assert not issubclass(transcribir.NoSeEntendio, transcribir.SinTranscriptor)
    assert not issubclass(transcribir.SinTranscriptor, transcribir.NoSeEntendio)


def test_un_codigo_de_salida_distinto_de_cero_trae_el_stderr_dentro(audio):
    """Lo que falla aquí suele ser un modelo sin descargar o un ffmpeg que no
    está, y esos mensajes traen el remedio dentro. Resumirlos lo quita."""
    ajustes = con_comando(guion(
        'import sys; sys.stderr.write("no encuentro el modelo base"); sys.exit(2)'
    ))
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.transcribir(audio, ajustes)

    assert "no encuentro el modelo base" in str(exc.value)
    assert "2" in str(exc.value)


def test_el_codigo_3_del_guion_del_hub_es_no_haberse_entendido_y_no_un_fallo(audio, tmp_path):
    """C-0150: `transcribir-whisper.py` sale con 3 cuando no oye nada (un
    dictado de silencio). Tomarlo por fallo enseñaba «el transcriptor salió con
    código 3» en el dictado y, en los encargos, metía el audio mudo en la cola
    de reintentos hasta rendirse por plazo."""
    guion_del_hub = tmp_path / "transcribir-whisper.py"
    guion_del_hub.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
    ajustes = con_comando([sys.executable, str(guion_del_hub), "{audio}"])
    with pytest.raises(transcribir.NoSeEntendio) as exc:
        transcribir.transcribir(audio, ajustes)
    assert "código" not in str(exc.value)
    assert "no se entendió" in str(exc.value)


def test_el_codigo_3_de_otro_transcriptor_es_un_fallo_y_no_silencio(audio):
    """C-0186: el 3 es el contrato de NUESTRO guion, no de cualquier programa.
    Uno declarado en `encargos.yml` que saliera con 3 por un fallo entregaba
    el audio como «no se entendió nada» al instante, sin reintentar, y el
    agente le pedía que lo repitiera por una avería de la máquina."""
    ajustes = con_comando(guion('import sys; sys.stderr.write("sin modelo"); sys.exit(3)'))
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.transcribir(audio, ajustes)
    assert "código 3" in str(exc.value) and "sin modelo" in str(exc.value)


def test_una_salida_vacia_es_no_haberse_entendido_y_no_un_fallo(audio):
    """Devolver `""` en vez de levantar haría indistinguibles los dos casos
    justo donde hay que distinguirlos: quien llama no sabría si reintentar."""
    ajustes = con_comando(guion('print("   ")'))
    with pytest.raises(transcribir.NoSeEntendio):
        transcribir.transcribir(audio, ajustes)


def test_un_ejecutable_que_no_existe_sale_como_sin_transcriptor(audio):
    """Y no como un `FileNotFoundError` desnudo.

    Quien llama atrapa los dos errores de este módulo; un tercero que se escapa
    tumba la vuelta del relé, y encima con un mensaje que habla de archivos
    —lo que hace pensar en el audio, no en la configuración.
    """
    ajustes = con_comando(["/opt/no-instalado/whisper.sh", "{audio}"])
    with pytest.raises(transcribir.SinTranscriptor) as exc:
        transcribir.transcribir(audio, ajustes)
    assert "/opt/no-instalado/whisper.sh" in str(exc.value)


def test_una_transcripcion_que_se_eterniza_se_corta_en_vez_de_colgar_el_rele(
    audio, monkeypatch
):
    """El relé es un solo proceso y atiende a todo el mundo.

    Un transcriptor que se queda pensando no deja un encargo sin contestar: los
    deja todos. El tope se baja aquí para no tener que esperar los 300 s reales.
    """
    monkeypatch.setattr(transcribir, "TOPE_SEGUNDOS", 1)
    ajustes = con_comando(guion("import time; time.sleep(30)"))

    with pytest.raises(transcribir.SinTranscriptor, match="se cortó"):
        transcribir.transcribir(audio, ajustes)


# ── lo que Whisper se inventa en el silencio ─────────────────────────────────

@pytest.mark.parametrize("texto", ["Subtítulos por la comunidad de Amara.org", "¡Gracias por ver!",
                                   "Thanks for watching!", "[Música]", "...", "Suscríbete al canal."])
def test_una_alucinacion_de_whisper_no_cuenta_como_dicho(texto):
    from hub import transcribir
    assert transcribir.alucinacion(texto)


@pytest.mark.parametrize("texto", ["Gracias por ver el informe, Ana", "Pon música en la sala",
                                   "recuérdame suscribirme al canal de Slack"])
def test_una_frase_real_que_las_contiene_si_cuenta(texto):
    from hub import transcribir
    assert not transcribir.alucinacion(texto)


# ── Whisper cargado (decisión 325) ───────────────────────────────────────────
# El servidor de estos tests es el guion de verdad, con un `faster_whisper` de
# mentira delante en el PYTHONPATH: lo que se prueba es el protocolo, el socket
# y sus límites, no Whisper.

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

GUION_SERVIDOR = Path(__file__).resolve().parent.parent / "scripts" / "transcribir-servidor.py"


@pytest.fixture
def servidor(tmp_path):
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "class _T:\n    def __init__(s, t): s.text = t\n"
        "class WhisperModel:\n    def __init__(s, *a, **k): pass\n"
        "    def transcribe(s, ruta, **k):\n"
        "        otro = '' if k.get('language') == 'es' else '[' + str(k.get('language')) + '] '\n"
        "        return [_T(' ' + otro + 'oído: ' + open(ruta).read() + ' ')], None\n")
    voz = tmp_path / "voz"
    voz.mkdir()
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "5"],
                         env={**os.environ, "PYTHONPATH": str(falso)})
    for _ in range(100):
        if enchufe.exists():
            break
        time.sleep(0.05)
    yield voz
    p.terminate()
    p.wait(5)


def test_con_el_servidor_vivo_el_dictado_va_por_el_y_no_arranca_otro(servidor, monkeypatch):
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    audio = servidor / "frase.webm"
    audio.write_text("hola secretario")
    assert transcribir._servidor(audio) == "oído: hola secretario"
    assert arrancados == []
    assert oct((servidor / "whisper.sock").stat().st_mode & 0o777) == "0o600"


def test_si_la_gpu_falla_el_servidor_carga_en_cpu_y_transcribe_igual(tmp_path):
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "class _T:\n    def __init__(s, t): s.text = t\n"
        "class WhisperModel:\n"
        "    def __init__(s, *a, device='cpu', **k):\n"
        "        if device == 'cuda': raise RuntimeError('Library libcublas.so.12 is not found')\n"
        "        s.device = device\n"
        "    def transcribe(s, ruta, **k):\n"
        "        return [_T(s.device + ': ' + open(ruta).read())], None\n")
    voz = tmp_path / "voz"
    voz.mkdir()
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "5"],
                         env={**os.environ, "PYTHONPATH": str(falso)}, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if enchufe.exists():
                break
            time.sleep(0.05)
        audio = voz / "frase.webm"
        audio.write_text("hola")
        assert transcribir._servidor(audio) == "cpu: hola"
    finally:
        p.terminate()
        p.wait(5)
    assert "voy por CPU" in p.stderr.read()


def test_el_servidor_no_transcribe_nada_de_fuera_de_su_carpeta(servidor, tmp_path):
    import socket
    fuera = tmp_path / "otro.webm"
    fuera.write_text("x")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        c.connect(str(servidor / "whisper.sock"))
        c.sendall((str(fuera) + "\n").encode())
        assert "sólo transcribo" in json.loads(c.makefile().readline())["error"]


def test_sin_servidor_se_arranca_para_la_proxima_y_esta_frase_sigue_por_el_camino_de_siempre(tmp_path, monkeypatch):
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    audio = tmp_path / "frase.webm"
    audio.write_text("x")
    assert transcribir._servidor(audio) is None
    assert arrancados == [tmp_path / "whisper.sock"]
    # Recién arrancado no se vuelve a lanzar: está cargando el modelo.
    assert transcribir._servidor(audio) is None and len(arrancados) == 1


def test_un_socket_huerfano_se_quita_y_no_rompe_el_dictado(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribir, "_arrancar_servidor", lambda e: None)
    (tmp_path / "whisper.sock").write_text("")   # no es un socket: nadie escucha
    audio = tmp_path / "frase.webm"
    audio.write_text("x")
    assert transcribir._servidor(audio) is None
    assert not (tmp_path / "whisper.sock").exists()


# ── el servidor también para lo declarado, si es lo mismo (C-0155) ───────────

def test_lo_declarado_con_nuestro_guion_tal_cual_va_por_el_servidor_con_su_interprete():
    from hub import config
    declarado = con_comando(["/otro/python", str(config.RAIZ_REPO / "scripts" / "transcribir-whisper.py"), "{audio}"])
    assert transcribir._python_del_servidor(declarado) == "/otro/python"


@pytest.mark.parametrize("extra", [["--modelo", "large-v3"], ["--idioma", "en"]])
def test_lo_declarado_con_otro_modelo_o_idioma_manda_y_no_pasa_por_el_servidor(extra):
    from hub import config
    linea = ["/otro/python", str(config.RAIZ_REPO / "scripts" / "transcribir-whisper.py"), "{audio}", *extra]
    assert transcribir._python_del_servidor(con_comando(linea)) is None


def test_otro_transcriptor_declarado_no_pasa_por_el_servidor():
    assert transcribir._python_del_servidor(con_comando(["whisper-cli", "{audio}"])) is None


def test_sin_nada_declarado_el_servidor_usa_el_de_por_omision():
    assert transcribir._python_del_servidor({}) == ""


def test_el_servidor_de_lo_declarado_se_arranca_con_su_interprete(tmp_path, monkeypatch):
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", lambda e, py="": arrancados.append(py))
    audio = tmp_path / "frase.webm"
    audio.write_text("x")
    assert transcribir._servidor(audio, "/otro/python") is None
    assert arrancados == ["/otro/python"]


# ── el idioma por petición (C-0159, el modo inglés) ──────────────────────────

def test_el_servidor_transcribe_en_ingles_si_se_le_pide(servidor, monkeypatch):
    monkeypatch.setattr(transcribir, "_arrancar_servidor", lambda *a: None)
    audio = servidor / "frase.webm"
    audio.write_text("hello there")
    assert transcribir._servidor(audio, idioma="en") == "[en] oído: hello there"
    # Y en español, como siempre: la ruta sola.
    assert transcribir._servidor(audio) == "oído: hello there"


def test_el_servidor_no_acepta_un_idioma_cualquiera_y_usa_el_suyo(servidor, monkeypatch):
    import socket
    audio = servidor / "frase.webm"
    audio.write_text("hola")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        c.connect(str(servidor / "whisper.sock"))
        c.sendall((json.dumps({"ruta": str(audio), "idioma": "xx; rm -rf"}) + "\n").encode())
        assert json.loads(c.makefile("r").readline())["texto"] == "oído: hola"


def test_sin_servidor_el_ingles_va_por_nuestro_guion_con_su_idioma(tmp_path, monkeypatch):
    from hub import config
    vistos = []
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    monkeypatch.setattr(transcribir, "_servidor", lambda *a: None)
    monkeypatch.setattr(transcribir, "por_omision",
                        lambda: ["/py", str(config.RAIZ_REPO / "scripts" / "transcribir-whisper.py"), "{audio}"])
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: vistos.append(aj) or "hello")
    assert transcribir.dictado(b"x", "a.webm", "en") == "hello"
    assert vistos[0]["transcripcion"]["comando"][-2:] == ["--idioma", "en"]


def test_un_idioma_que_no_es_de_la_conversacion_se_rechaza_sin_dejar_el_audio(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    with pytest.raises(ValueError, match="idioma"):
        transcribir.dictado(b"x", "a.webm", "fr")
    assert not (tmp_path / "voz").exists() or not list((tmp_path / "voz").glob("*"))


def test_en_ingles_otro_transcriptor_declarado_lo_dice_en_vez_de_inventar(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    (tmp_path / "encargos.yml").write_text('transcripcion: {comando: ["whisper-cli", "{audio}"]}')
    monkeypatch.setattr(config, "encargos_yml", lambda: tmp_path / "encargos.yml")
    with pytest.raises(ValueError, match="no sabe cambiar de idioma"):
        transcribir.dictado(b"x", "a.webm", "en")
    assert not list((tmp_path / "voz").glob("*"))


# ── el audio que se queda tras un dictado fallido (C-0126) ───────────────────


def test_el_audio_de_un_dictado_fallido_se_poda_a_los_diez_dias_y_nada_mas(tmp_path, monkeypatch):
    """Se queda para poder mirar qué pasó, no para siempre: nadie lo guardó a
    propósito, como lo pegado en la terminal (decisiones 288 y 362). El socket
    del Whisper cargado vive en la misma carpeta y no se toca nunca."""
    import os
    import time

    from hub import config

    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    voz = tmp_path / "voz"
    voz.mkdir()
    ahora = time.time()
    viejo = voz / "261020-101010-1.webm"
    nuevo = voz / "261105-101010-2.webm"
    marca = voz / "whisper.arrancando"
    otro = voz / "notas.txt"
    for f in (viejo, nuevo, marca, otro):
        f.write_bytes(b"x")
    hace_once_dias = ahora - 11 * 86400
    for f in (viejo, marca, otro):
        os.utime(f, (hace_once_dias, hace_once_dias))

    assert transcribir.podar_dictados(ahora) == 1
    assert not viejo.exists()
    assert nuevo.exists() and marca.exists() and otro.exists()


def test_sin_carpeta_de_voz_podar_no_hace_nada(tmp_path, monkeypatch):
    from hub import config

    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    assert transcribir.podar_dictados() == 0
    assert not (tmp_path / "voz").exists()


def test_el_ciclo_lento_poda_los_dictados(tmp_path, monkeypatch):
    from hub import db, snapshotter

    llamado = []
    monkeypatch.setattr(transcribir, "podar_dictados", lambda: llamado.append(1) or 0)
    con = db.conectar(tmp_path / "hub.db")
    db.inicializar(con)
    assert snapshotter.ciclo_lento(con)["dictados"] == 0
    assert llamado


def test_si_el_servidor_de_whisper_no_arranca_se_dice(monkeypatch, tmp_path, capsys):
    """Un `except OSError: pass` al arrancarlo (C-0124): sin servidor cada
    dictado carga el modelo de cero, más lento, y nada decía por qué."""
    from hub import procesos

    def falla(*a, **k):
        raise OSError("no hay python")

    monkeypatch.setattr(procesos, "desasir", falla)
    transcribir._arrancar_servidor(tmp_path / "whisper.sock", python="/no/python")
    assert "no hay python" in capsys.readouterr().out


# ── lo que se mide de cada dictado (C-0246) ──────────────────────────────────

def test_el_servidor_responde_con_lo_que_midio_y_sin_el_texto_aparte(servidor):
    audio = servidor / "frase.webm"
    audio.write_text("hola secretario")
    medidas = {}
    assert transcribir._servidor(audio, medidas=medidas) == "oído: hola secretario"
    assert set(medidas) >= {"ms_whisper", "modelo", "dispositivo", "s_audio", "s_voz"}
    assert medidas["dispositivo"] == "cuda" and medidas["modelo"] == "small"   # el falso no falla al cargar la GPU
    assert "hola" not in json.dumps(medidas)


def test_el_dictado_dice_por_que_camino_fue(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: "hola")
    monkeypatch.setattr(transcribir, "_servidor", lambda *a: None)
    for python, camino in (("", "frio"), (None, "declarado")):
        monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj, p=python: p)
        medidas = {}
        assert transcribir.dictado(b"x", "a.webm", "es", medidas) == "hola"
        assert medidas["camino"] == camino and medidas["ms_whisper"] >= 0

    def servidor_vivo(ruta, python, idioma, medidas, con_glosario=None):
        medidas.update({"ms_whisper": 7, "modelo": "small", "dispositivo": "cuda"})
        return "hola"
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: "")
    monkeypatch.setattr(transcribir, "_servidor", servidor_vivo)
    medidas = {}
    transcribir.dictado(b"x", "a.webm", "es", medidas)
    assert medidas["camino"] == "servidor" and medidas["dispositivo"] == "cuda" and medidas["ms_whisper"] == 7


def test_el_origen_se_valida_contra_una_lista_cerrada():
    assert transcribir.origen_valido("tablero") == "tablero"
    assert transcribir.origen_valido("") == "desconocido"
    assert transcribir.origen_valido("x; rm -rf") == "desconocido"
    assert transcribir.origen_valido(None) == "desconocido"


def test_la_linea_del_journal_no_deja_pasar_nada_fuera_de_su_lista():
    linea = transcribir.linea_de_medidas({"resultado": "ok", "origen": "secretario", "camino": "servidor",
                                          "ms_total": 900, "texto": "mi secreto", "caracteres": 10})
    assert "mi secreto" not in linea and "\n" not in linea
    assert "resultado=ok" in linea and "caracteres=10" in linea and "ms_whisper=-" in linea


def test_arrancar_el_servidor_le_da_su_registro_acotado_a_las_ultimas_lineas(monkeypatch, tmp_path):
    from hub import procesos
    voz = tmp_path / "voz"
    voz.mkdir()
    (voz / "servidor.log").write_text("".join(f"linea {i}\n" for i in range(500)))
    vistos = {}
    monkeypatch.setattr(procesos, "desasir", lambda orden, **k: vistos.update(k))
    transcribir._arrancar_servidor(voz / "whisper.sock", python="/py")
    assert vistos["salida"] is not None and vistos["salida"].name == str(voz / "servidor.log")
    lineas = (voz / "servidor.log").read_text().splitlines()
    assert len(lineas) == transcribir.LINEAS_REGISTRO_SERVIDOR and lineas[-1] == "linea 499"


def test_el_servidor_escribe_su_arranque_en_su_salida_de_error(tmp_path):
    """Lo que `servidor.log` recibe: la línea de «cargado en …», y los errores sin lo dictado."""
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "class WhisperModel:\n    def __init__(s, *a, **k): pass\n"
        "    def transcribe(s, ruta, **k): raise RuntimeError('cuda se cayó')\n")
    voz = tmp_path / "voz"
    voz.mkdir()
    registro = voz / "servidor.log"
    audio = voz / "a.webm"
    audio.write_text("mi secreto")
    with open(registro, "w") as f:
        p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(voz / "whisper.sock"), "--ocioso", "3"],
                             env={**os.environ, "PYTHONPATH": str(falso)}, stdout=f, stderr=subprocess.STDOUT)
        for _ in range(100):
            if (voz / "whisper.sock").exists():
                break
            time.sleep(0.05)
        import socket
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.connect(str(voz / "whisper.sock"))
            c.sendall((str(audio) + "\n").encode())
            c.makefile("r").readline()
        p.terminate()
        p.wait(5)
    texto = registro.read_text()
    assert "cargado en" in texto and "cuda se cayó" in texto and "mi secreto" not in texto


def test_api_voz_deja_una_linea_con_el_resultado_y_nunca_el_texto(monkeypatch, capsys):
    from fastapi.testclient import TestClient

    from hub import web

    def falso(datos, nombre, idioma="es", medidas=None):
        medidas.update({"camino": "servidor", "ms_whisper": 120, "modelo": "small",
                        "dispositivo": "cuda", "s_audio": 3.2, "s_voz": 2.9})
        if datos == b"mudo":
            raise transcribir.NoSeEntendio("nada")
        if datos == b"roto":
            raise transcribir.SinTranscriptor("no hay")
        return "contraseña del banco"

    monkeypatch.setattr(transcribir, "dictado", falso)
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    cabeceras = {"Origin": "http://127.0.0.1:8787"}

    def pedir(datos, **campos):
        capsys.readouterr()
        r = cliente.post("/api/voz", files={"audio": ("a.webm", datos)}, data=campos, headers=cabeceras)
        return r, [l for l in capsys.readouterr().out.splitlines() if l.startswith("[voz]")]

    r, lineas = pedir(b"bien", origen="tablero")
    assert r.status_code == 200 and r.json()["texto"] == "contraseña del banco"
    assert r.json()["medidas"]["resultado"] == "ok" and r.json()["medidas"]["camino"] == "servidor"
    assert len(lineas) == 1
    assert "contraseña" not in lineas[0] and "banco" not in lineas[0]
    for esperado in ("resultado=ok", "origen=tablero", "camino=servidor", "modelo=small", "dispositivo=cuda",
                     "s_audio=3.2", "s_voz=2.9", "ms_whisper=120", "caracteres=20"):
        assert esperado in lineas[0]
    assert "ms_total=" in lineas[0] and "ms_total=-" not in lineas[0]

    r, lineas = pedir(b"mudo")
    assert r.status_code == 200 and "resultado=nada" in lineas[0] and "origen=desconocido" in lineas[0]
    r, lineas = pedir(b"roto", origen="inventado")
    assert r.json()["ok"] is False and "resultado=fallo" in lineas[0] and "origen=desconocido" in lineas[0]


def test_api_voz_distingue_no_haber_oido_palabras_de_un_fallo(monkeypatch):
    """Una tos o una puerta no son un error (C-0286): el modo voz pregunta y
    sigue escuchando con `nada`, y sólo se pausa con un fallo de verdad."""
    from fastapi.testclient import TestClient

    from hub import web

    def falso(datos, nombre, idioma="es", medidas=None):
        if datos == b"tos":
            raise transcribir.NoSeEntendio("no se oyó a nadie hablar")
        raise transcribir.SinTranscriptor("no hay transcriptor")

    monkeypatch.setattr(transcribir, "dictado", falso)
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    cabeceras = {"Origin": "http://127.0.0.1:8787"}
    tos = cliente.post("/api/voz", files={"audio": ("a.webm", b"tos")}, headers=cabeceras).json()
    roto = cliente.post("/api/voz", files={"audio": ("a.webm", b"roto")}, headers=cabeceras).json()
    assert tos["ok"] is False and tos["nada"] is True
    assert roto["ok"] is False and "nada" not in roto


# ── calentar al empezar a grabar (C-0292) ────────────────────────────────────
# Uno de cada cuatro dictados llegaba con el servidor ya apagado y se pagaba
# entero en la CPU, cargando el modelo. Ahora se arranca al empezar a grabar,
# y la frase espera a que acabe de cargar en vez de cargar otro modelo.

@pytest.fixture
def casa(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "HUB_HOME", tmp_path)
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: "")
    monkeypatch.setattr(transcribir, "por_omision", lambda: ["/py", "guion", "{audio}"])
    return tmp_path / "voz"


def test_calentar_arranca_el_servidor_una_vez_y_no_dos(casa, monkeypatch):
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    assert transcribir.calentar() == "arrancando"
    assert transcribir.calentar() == "arrancando"      # está cargando: no se lanza otro
    assert arrancados == [casa / "whisper.sock"]
    # El dictado que llega mientras tanto tampoco lanza otro.
    audio = casa / "frase.webm"
    audio.write_text("x")
    assert transcribir._servidor(audio) is None and len(arrancados) == 1


def test_con_el_servidor_ya_cargado_calentar_no_hace_nada(casa, monkeypatch):
    import socket
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    casa.mkdir()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as escucha:
        escucha.bind(str(casa / "whisper.sock"))
        escucha.listen(4)
        assert transcribir.calentar() == "listo" and arrancados == []


def test_con_otro_transcriptor_declarado_calentar_no_arranca_nada(casa, monkeypatch):
    """Lo declarado manda (325): si no es nuestro guion, no hay servidor que calentar."""
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    monkeypatch.setattr(transcribir, "_python_del_servidor", lambda aj: None)
    assert transcribir.calentar() == "no" and arrancados == []


def _servidor_que_tarda_en_cargar(tmp_path, carga_s: float):
    """El guion de verdad con un faster_whisper falso que tarda en cargar."""
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "import time\n"
        "class _T:\n    def __init__(s, t): s.text = t\n"
        f"class WhisperModel:\n    def __init__(s, *a, **k): time.sleep({carga_s})\n"
        "    def transcribe(s, ruta, **k):\n"
        "        if not isinstance(ruta, str): return iter(()), None\n"
        "        return [_T('oído: ' + open(ruta).read())], None\n")
    voz = tmp_path / "voz"
    voz.mkdir(exist_ok=True)
    return voz, falso


def test_la_frase_que_llega_mientras_carga_espera_al_servidor_y_no_carga_otro_en_cpu(tmp_path, monkeypatch):
    from hub import procesos
    voz, falso = _servidor_que_tarda_en_cargar(tmp_path, 0.8)
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "5"],
                         env={**os.environ, "PYTHONPATH": str(falso)})
    try:
        # Como lo deja `calentar`: la marca con la huella del que carga.
        (voz / "whisper.arrancando").write_text(json.dumps(procesos.huella(p.pid)))
        arrancados = []
        monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
        audio = voz / "frase.webm"
        audio.write_text("hola")
        assert transcribir._servidor(audio) == "oído: hola"
        assert arrancados == []
    finally:
        p.terminate()
        p.wait(5)


def test_si_el_que_cargaba_murio_no_se_le_espera(tmp_path, monkeypatch):
    """Un servidor que no arranca (sin faster-whisper) no puede costar la espera
    entera en cada frase: se mira si sigue vivo."""
    from hub import procesos
    muerto = subprocess.Popen([sys.executable, "-c", "pass"])
    muerto.wait(5)
    voz = tmp_path / "voz"
    voz.mkdir()
    (voz / "whisper.arrancando").write_text(json.dumps({"pid": muerto.pid, "arranque": "0"}))
    monkeypatch.setattr(transcribir, "_arrancar_servidor", lambda *a: None)
    audio = voz / "frase.webm"
    audio.write_text("x")
    t0 = time.monotonic()
    assert transcribir._servidor(audio) is None
    assert time.monotonic() - t0 < 1
    assert procesos.vivo({"pid": muerto.pid, "arranque": "0"}) is False


def test_arrancar_deja_en_la_marca_la_huella_del_que_carga(tmp_path, monkeypatch):
    from hub import procesos

    class Lanzado:
        pid = os.getpid()
    monkeypatch.setattr(procesos, "desasir", lambda orden, **k: Lanzado())
    voz = tmp_path / "voz"
    voz.mkdir()
    audio = voz / "frase.webm"
    audio.write_text("x")
    assert transcribir._servidor(audio, python="/py") is None
    assert json.loads((voz / "whisper.arrancando").read_text()) == procesos.huella(os.getpid())


def test_el_servidor_se_calienta_con_silencio_antes_de_abrir_el_socket(tmp_path):
    """La primera llamada en la GPU inicializa cuBLAS y cuDNN: la pagaba la
    primera frase. Sin VAD, que con silencio no deja pasar nada al modelo."""
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "import json, os, sys\n"
        "class WhisperModel:\n    def __init__(s, *a, **k): pass\n"
        "    def transcribe(s, audio, **k):\n"
        "        if not isinstance(audio, str):\n"
        "            datos = audio.read()\n"
        "            with open(os.path.join(os.path.dirname(sys.argv[1]), 'calentado.json'), 'w') as f:\n"
        "                json.dump({'riff': datos[:4].decode('latin-1'), 'vad': k.get('vad_filter'),\n"
        "                           'socket_ya': os.path.exists(sys.argv[1])}, f)\n"
        "        return iter(()), None\n")
    voz = tmp_path / "voz"
    voz.mkdir()
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "5"],
                         env={**os.environ, "PYTHONPATH": str(falso)})
    try:
        for _ in range(100):
            if enchufe.exists():
                break
            time.sleep(0.05)
        assert enchufe.exists()
    finally:
        p.terminate()
        p.wait(5)
    assert json.loads((voz / "calentado.json").read_text()) == {"riff": "RIFF", "vad": False, "socket_ya": False}


def test_api_voz_calentar_contesta_en_que_quedo_y_pide_mismo_origen(monkeypatch):
    from fastapi.testclient import TestClient

    from hub import web
    monkeypatch.setattr(transcribir, "calentar", lambda: "arrancando")
    cliente = TestClient(web.app, base_url="http://127.0.0.1:8787")
    r = cliente.post("/api/voz/calentar", headers={"Origin": "http://127.0.0.1:8787"})
    assert r.json() == {"ok": True, "estado": "arrancando"}
    ajeno = cliente.post("/api/voz/calentar", headers={"Origin": "https://malo.example"})
    assert ajeno.status_code == 403


# ── la puerta del servidor, ampliada para medir (C-0312, paso P0) ────────────
# El banco de dictado arranca un servidor por configuración, le pide cada
# audio y lo apaga. Para eso hacen falta el tipo de cálculo, preguntarle qué
# tiene cargado y apagarlo sin matar por patrón: por el pid que da el propio
# socket (`SO_PEERCRED`), comprobado con su huella.

def _falso_que_anota(tmp_path, carga_s: float = 0.0, cuda_falla: bool = False):
    """Un faster_whisper falso que deja escrito con qué se cargó."""
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True, exist_ok=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "import json, os, sys, time\n"
        "class _T:\n    def __init__(s, t): s.text = t\n"
        "class WhisperModel:\n"
        "    def __init__(s, nombre, device='cpu', compute_type='', **k):\n"
        f"        time.sleep({carga_s})\n"
        f"        if {cuda_falla!r} and device == 'cuda': raise RuntimeError('sin libcublas')\n"
        "        with open(os.path.join(os.path.dirname(sys.argv[1]), 'cargado.json'), 'w') as f:\n"
        "            json.dump({'nombre': nombre, 'device': device, 'tipo': compute_type}, f)\n"
        "    def transcribe(s, ruta, **k):\n"
        "        if not isinstance(ruta, str): return iter(()), None\n"
        "        return [_T('oído: ' + open(ruta).read())], None\n")
    return falso


def _lanzar(tmp_path, *extra, carga_s: float = 0.0, cuda_falla: bool = False, esperar: bool = True):
    falso = _falso_que_anota(tmp_path, carga_s, cuda_falla)
    voz = tmp_path / "voz"
    voz.mkdir(exist_ok=True)
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "20", *extra],
                         env={**os.environ, "PYTHONPATH": str(falso)})
    if esperar:
        for _ in range(200):
            if enchufe.exists():
                break
            time.sleep(0.05)
    return p, enchufe


def test_el_servidor_dice_que_tiene_cargado_con_su_tipo_y_su_pid(tmp_path):
    p, enchufe = _lanzar(tmp_path, "--tipo", "int8_float16")
    try:
        estado = transcribir.estado_servidor(enchufe)
    finally:
        p.terminate()
        p.wait(5)
    assert estado["modelo"] == "small" and estado["dispositivo"] == "cuda"
    assert estado["tipo"] == "int8_float16" and estado["pid"] == p.pid
    assert estado["s_carga"] >= 0
    assert json.loads((enchufe.parent / "cargado.json").read_text())["tipo"] == "int8_float16"


def test_sin_tipo_el_servidor_carga_el_de_siempre_y_lo_dice_en_las_medidas(tmp_path):
    p, enchufe = _lanzar(tmp_path)
    try:
        audio = enchufe.parent / "frase.webm"
        audio.write_text("hola")
        medidas = {}
        assert transcribir._servidor(audio, medidas=medidas) == "oído: hola"
    finally:
        p.terminate()
        p.wait(5)
    assert medidas["tipo"] == "float16" and medidas["dispositivo"] == "cuda"


def test_si_la_gpu_cae_el_tipo_pedido_para_ella_no_se_le_impone_a_la_cpu(tmp_path):
    """`float16` en la CPU no carga: se cae a la de siempre (`int8`) y se dice
    cuál quedó, que es lo que mide el banco."""
    p, enchufe = _lanzar(tmp_path, "--tipo", "float16", cuda_falla=True)
    try:
        estado = transcribir.estado_servidor(enchufe)
    finally:
        p.terminate()
        p.wait(5)
    assert estado["dispositivo"] == "cpu" and estado["tipo"] == "int8"


def test_apagar_le_pide_que_salga_y_no_queda_ni_el_proceso_ni_el_socket(tmp_path):
    from hub import procesos
    p, enchufe = _lanzar(tmp_path)
    try:
        huella = procesos.huella(p.pid)
        assert transcribir.apagar_servidor(enchufe) is True
        assert p.wait(5) == 0          # salió solo, no por una señal
        assert not procesos.vivo(huella)
        assert not enchufe.exists()
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(5)


def test_sin_servidor_apagar_no_hace_nada(tmp_path):
    assert transcribir.apagar_servidor(tmp_path / "voz" / "whisper.sock") is False


def _servidor_viejo(tmp_path, nombre: str, contesta: bool = True):
    """Un servidor de antes de las órdenes: a todo contesta que sólo transcribe
    audios de su carpeta (o no contesta nada). Se llama como el guion porque
    apagar comprueba que el pid sea de verdad el del servidor de Whisper."""
    guion = tmp_path / nombre
    guion.write_text(
        "import json, socket, sys, time\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "s.bind(sys.argv[1]); s.listen(4)\n"
        "while True:\n"
        "    c, _ = s.accept()\n"
        "    c.makefile('r').readline()\n"
        f"    if {contesta!r}:\n"
        "        c.sendall((json.dumps({'error': 'sólo transcribo audios de la carpeta de voz del hub'}) + '\\n').encode())\n"
        "    else:\n"
        "        time.sleep(30)\n"
        "    c.close()\n")
    voz = tmp_path / "voz"
    voz.mkdir(exist_ok=True)
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(guion), str(enchufe)])
    for _ in range(100):
        if enchufe.exists():
            break
        time.sleep(0.05)
    return p, enchufe


@pytest.mark.parametrize("contesta", [True, False], ids=["contesta-que-no-sabe", "no-contesta"])
def test_un_servidor_que_no_sabe_apagarse_se_para_por_el_pid_de_su_socket(tmp_path, contesta, monkeypatch):
    monkeypatch.setattr(transcribir, "ESPERA_ORDEN_S", 0.5)
    p, enchufe = _servidor_viejo(tmp_path, "transcribir-servidor.py", contesta)
    try:
        assert transcribir.apagar_servidor(enchufe, espera=0.5) is True
        assert p.wait(5) != 0          # por la señal
        assert not enchufe.exists()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_apagar_no_mata_lo_que_escucha_en_el_socket_si_no_es_el_servidor_de_whisper(tmp_path, monkeypatch):
    """Por pid y comprobado, nunca por patrón: si lo que tiene el socket no es
    nuestro guion, no se le manda ninguna señal y se dice."""
    monkeypatch.setattr(transcribir, "ESPERA_ORDEN_S", 0.5)
    p, enchufe = _servidor_viejo(tmp_path, "otra-cosa.py", contesta=False)
    try:
        with pytest.raises(RuntimeError, match="no es el servidor de Whisper"):
            transcribir.apagar_servidor(enchufe, espera=0.5)
        assert p.poll() is None
    finally:
        p.kill()
        p.wait(5)


def test_apagar_al_que_aun_carga_lo_para_por_la_huella_de_su_marca(tmp_path):
    """Sin socket todavía (está cargando el modelo): su marca lleva la huella."""
    from hub import procesos
    p, enchufe = _lanzar(tmp_path, carga_s=5, esperar=False)
    try:
        time.sleep(0.3)
        (enchufe.parent / "whisper.arrancando").write_text(json.dumps(procesos.huella(p.pid)))
        assert transcribir.apagar_servidor(enchufe) is True
        assert p.wait(5) != 0
        assert not (enchufe.parent / "whisper.arrancando").exists()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_pedir_sin_nadie_escuchando_devuelve_none(tmp_path):
    assert transcribir.pedir(tmp_path / "nadie.sock", {"orden": "estado"}, 1) is None


def test_arrancar_servidor_pasa_modelo_tipo_y_ocioso_y_el_del_dictado_sigue_igual(tmp_path, monkeypatch):
    from hub import procesos
    ordenes = []
    monkeypatch.setattr(procesos, "desasir", lambda orden, **k: ordenes.append(orden))
    voz = tmp_path / "voz"
    voz.mkdir()
    transcribir._arrancar_servidor(voz / "whisper.sock", python="/py")
    transcribir.arrancar_servidor(voz / "medir.sock", python="/py", modelo="large-v3-turbo",
                                  tipo="int8_float16", dispositivo="cuda", ocioso=120)
    assert ordenes[0][2:] == [str(voz / "whisper.sock")]   # el dictado, como siempre
    assert ordenes[1][2:] == [str(voz / "medir.sock"), "--modelo", "large-v3-turbo", "--tipo", "int8_float16",
                              "--dispositivo", "cuda", "--ocioso", "120"]


@pytest.mark.parametrize("campo,valor", [("modelo", "--ocioso"), ("tipo", "a b"), ("dispositivo", "tpu")])
def test_arrancar_servidor_no_acepta_valores_que_no_son_un_nombre(tmp_path, monkeypatch, campo, valor):
    from hub import procesos
    monkeypatch.setattr(procesos, "desasir", lambda orden, **k: pytest.fail("se lanzó con un valor raro"))
    with pytest.raises(ValueError):
        transcribir.arrancar_servidor(tmp_path / "medir.sock", python="/py", **{campo: valor})


def test_el_interprete_del_servidor_es_el_de_lo_declarado_si_es_nuestro_guion(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.setattr(config, "encargos_yml", lambda: tmp_path / "encargos.yml")
    assert transcribir.interprete_del_servidor() == ""          # nada declarado: el de por omisión
    (tmp_path / "encargos.yml").write_text('transcripcion: {comando: ["whisper-cli", "{audio}"]}')
    assert transcribir.interprete_del_servidor() is None        # otro programa: sin servidor


# ── lo que marcó el revisor (C-0312) ─────────────────────────────────────────

def test_apagar_no_corta_la_frase_que_se_esta_transcribiendo(tmp_path, monkeypatch):
    """El servidor atiende de una en una: la orden espera en la cola lo que
    tarda una frase, y no se pasa a SIGTERM a los 3 s con lo dictado a medias."""
    import threading
    monkeypatch.setattr(transcribir, "ESPERA_ORDEN_S", 0.5)
    falso = tmp_path / "falso"
    (falso / "faster_whisper").mkdir(parents=True)
    (falso / "faster_whisper" / "__init__.py").write_text(
        "import time\n"
        "class _T:\n    def __init__(s, t): s.text = t\n"
        "class WhisperModel:\n    def __init__(s, *a, **k): pass\n"
        "    def transcribe(s, ruta, **k):\n"
        "        if not isinstance(ruta, str): return iter(()), None\n"
        "        time.sleep(1.5)\n"
        "        return [_T('oído: ' + open(ruta).read())], None\n")
    voz = tmp_path / "voz"
    voz.mkdir()
    enchufe = voz / "whisper.sock"
    p = subprocess.Popen([sys.executable, str(GUION_SERVIDOR), str(enchufe), "--ocioso", "20"],
                         env={**os.environ, "PYTHONPATH": str(falso)})
    try:
        for _ in range(200):
            if enchufe.exists():
                break
            time.sleep(0.05)
        audio = voz / "frase.webm"
        audio.write_text("hola")
        dicho = {}
        hilo = threading.Thread(target=lambda: dicho.update(r=transcribir.pedir(enchufe, str(audio))))
        hilo.start()
        time.sleep(0.3)
        assert transcribir.apagar_servidor(enchufe) is True
        hilo.join(5)
        assert dicho["r"] and dicho["r"]["texto"] == "oído: hola"
        assert p.wait(5) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_sin_permiso_para_la_senal_se_dice_y_no_sale_una_traza(tmp_path, monkeypatch):
    p, enchufe = _servidor_viejo(tmp_path, "transcribir-servidor.py", contesta=True)
    try:
        with monkeypatch.context() as m:
            def sin_permiso(pid, senal):
                raise PermissionError(1, "Operation not permitted")
            m.setattr(os, "kill", sin_permiso)
            with pytest.raises(RuntimeError, match="permiso"):
                transcribir.apagar_servidor(enchufe, espera=0.5)
    finally:
        p.kill()
        p.wait(5)


class _Lanzado:
    pid = os.getpid()


def test_dos_arranques_a_la_vez_lanzan_un_solo_servidor(tmp_path, monkeypatch):
    """Sin cerrojo, los dos veían que no había marca ni socket y lanzaban: el
    segundo hacía `unlink`+`bind` y el primero, al salir, borraba el socket del vivo."""
    import threading
    from hub import procesos
    lanzados = []

    def lento(orden, **k):
        lanzados.append(orden)
        time.sleep(0.3)
        return _Lanzado()
    monkeypatch.setattr(procesos, "desasir", lento)
    voz = tmp_path / "voz"
    voz.mkdir()
    hilos = [threading.Thread(target=transcribir._arrancar_si_toca, args=(voz / "whisper.sock", "/py"))
             for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(5)
    assert len(lanzados) == 1


def test_la_marca_se_escribe_antes_de_lanzar_y_solo_para_el_dueno(tmp_path, monkeypatch):
    from hub import procesos
    voz = tmp_path / "voz"
    voz.mkdir()
    vista = {}

    def mira(orden, **k):
        vista["marca"] = (voz / "whisper.arrancando").exists()
        return _Lanzado()
    monkeypatch.setattr(procesos, "desasir", mira)
    transcribir.arrancar_servidor(voz / "whisper.sock", python="/py")
    assert vista["marca"] is True
    for nombre in ("whisper.arrancando", "servidor.log"):
        assert oct((voz / nombre).stat().st_mode & 0o777) == "0o600", nombre


def test_pasado_el_rato_no_se_relanza_si_el_que_cargo_sigue_vivo(tmp_path, monkeypatch):
    from hub import procesos
    monkeypatch.setattr(procesos, "desasir", lambda orden, **k: pytest.fail("se lanzó otro"))
    voz = tmp_path / "voz"
    voz.mkdir()
    marca = voz / "whisper.arrancando"
    marca.write_text(json.dumps(procesos.huella(os.getpid())))
    hace_un_minuto = time.time() - 60
    os.utime(marca, (hace_un_minuto, hace_un_minuto))
    assert transcribir._arrancar_si_toca(voz / "whisper.sock", "/py") is False


def test_un_socket_huerfano_no_es_un_servidor_listo_y_calentar_arranca_uno(casa, monkeypatch):
    """Tras un `kill -9` o un reinicio queda el archivo del socket y nadie
    escucha: «listo» mandaba la primera frase en frío."""
    import socket
    arrancados = []
    monkeypatch.setattr(transcribir, "_arrancar_servidor", arrancados.append)
    casa.mkdir()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as muerto:
        muerto.bind(str(casa / "whisper.sock"))   # se cierra sin escuchar: queda el archivo
    assert (casa / "whisper.sock").exists()
    assert transcribir.calentar() == "arrancando"
    assert arrancados == [casa / "whisper.sock"]
