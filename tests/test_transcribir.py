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
        assert json.loads(c.makefile("r").readline()) == {"texto": "oído: hola"}


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
